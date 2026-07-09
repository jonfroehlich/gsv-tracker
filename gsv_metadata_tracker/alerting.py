"""
Operator alerting for the scheduler (issue #92 deploy hardening).

Sends a short email when a nightly ``run-due`` finishes unhealthy (too many
failed collections, or a crash) so a deployment on makelab1 doesn't fail
silently. Deliberately transport-agnostic — the box may have a working
``mail`` relay, or need ``msmtp``/``sendmail``, or the operator may want a
custom command (e.g. a Slack webhook) — and OFF by default: nothing is sent
until ``[alerts] enabled = true`` and a recipient are configured.

Pure message/argv construction (``build_send_plan``) is separated from the
subprocess call (``send_alert``) so it is unit-testable without sending mail.
Alerting must never crash a collection run, so ``send_alert`` swallows and
logs its own errors and always returns a bool.
"""

import logging
import socket
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Known transports. "command" is the escape hatch: an arbitrary shell command
# that receives the body on stdin and the subject/recipient via the
# GSV_ALERT_SUBJECT / GSV_ALERT_TO environment variables.
TRANSPORTS = ("mail", "msmtp", "sendmail", "command")


@dataclass
class AlertConfig:
    """[alerts] section of scheduler.toml."""

    enabled: bool = False
    recipient: str = ""
    transport: str = "mail"
    command: str = ""  # used only when transport == "command"
    # Email when a run finishes with at least this many failed (city, provider)
    # collections. 1 = alert on any failure; raise it to cut noise from the
    # occasional flaky single city.
    failure_threshold: int = 1
    subject_prefix: str = "[gsv-tracker]"


def _message_with_headers(recipient: str, subject: str, body: str) -> str:
    """An RFC-822-ish message for SMTP-style transports (msmtp/sendmail)."""
    return (
        f"To: {recipient}\nSubject: {subject}\nFrom: gsv-tracker@{socket.gethostname()}\n\n{body}\n"
    )


def build_send_plan(
    transport: str, recipient: str, subject: str, body: str, command: str = ""
) -> tuple[object, str, bool]:
    """
    Resolve a transport to ``(cmd, stdin_text, use_shell)``:

    * ``mail``     -> ``["mail", "-s", subject, recipient]``, body on stdin.
    * ``msmtp``    -> ``["msmtp", recipient]`` fed a headered message.
    * ``sendmail`` -> ``["sendmail", "-t"]`` (recipient from the To: header).
    * ``command``  -> the raw shell string (use_shell=True); subject/recipient
      are exported to the environment by ``send_alert``, body on stdin.

    Kept free of side effects so tests can assert the exact argv/message.
    """
    if transport == "mail":
        return ["mail", "-s", subject, recipient], body, False
    if transport == "msmtp":
        return ["msmtp", recipient], _message_with_headers(recipient, subject, body), False
    if transport == "sendmail":
        return ["sendmail", "-t"], _message_with_headers(recipient, subject, body), False
    if transport == "command":
        if not command:
            raise ValueError('transport "command" requires [alerts] command')
        return command, body, True
    raise ValueError(f"unknown alert transport {transport!r} (known: {', '.join(TRANSPORTS)})")


def should_alert(failures: int, threshold: int) -> bool:
    """True when a completed run's failure count warrants an email."""
    return failures >= max(1, threshold)


def send_alert(cfg: AlertConfig, subject: str, body: str) -> bool:
    """
    Best-effort send. Returns True only if the transport command exited 0.
    Never raises: a broken mailer must not take down a collection run.
    """
    if not cfg.enabled:
        return False
    if not cfg.recipient and cfg.transport != "command":
        logger.warning("Alerts enabled but no [alerts] recipient set; skipping")
        return False

    full_subject = f"{cfg.subject_prefix} {subject}".strip()
    try:
        cmd, stdin_text, use_shell = build_send_plan(
            cfg.transport, cfg.recipient, full_subject, body, cfg.command
        )
    except ValueError as e:
        logger.error(f"Alert not sent — bad config: {e}")
        return False

    env = None
    if use_shell:
        import os

        env = {**os.environ, "GSV_ALERT_SUBJECT": full_subject, "GSV_ALERT_TO": cfg.recipient}
    try:
        result = subprocess.run(
            cmd,
            input=stdin_text.encode("utf-8"),
            shell=use_shell,
            env=env,
            timeout=30,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(f"Alert send failed ({cfg.transport}): {e}")
        return False
    if result.returncode != 0:
        logger.error(
            f"Alert transport {cfg.transport!r} exited "
            f"{result.returncode}: {result.stderr.decode('utf-8', 'replace')[:200]}"
        )
        return False
    logger.info(f"Alert emailed to {cfg.recipient or '(command)'}: {subject}")
    return True

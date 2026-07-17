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
import os
import smtplib
import socket
import subprocess
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger(__name__)

# Known transports. "command" is the escape hatch: an arbitrary shell command
# that receives the body on stdin and the subject/recipient via the
# STREETSCAPE_ALERT_SUBJECT / STREETSCAPE_ALERT_TO environment variables.
# "smtp" talks to a relay directly via stdlib smtplib — no local mailer,
# so it survives a hardened systemd sandbox (NoNewPrivileges blocks the
# setgid postdrop path that "mail"/sendmail need). See issue #144.
TRANSPORTS = ("mail", "msmtp", "sendmail", "command", "smtp")

# Env var an SMTP password may be read from, so the toml can stay secret-free.
SMTP_PASSWORD_ENV = "STREETSCAPE_ALERT_SMTP_PASSWORD"


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
    subject_prefix: str = "[streetscape-tracker]"
    # --- transport == "smtp" only (all optional but smtp_host) ---
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_from: str = ""  # defaults to streetscape-tracker@<hostname>
    smtp_starttls: bool = False
    smtp_user: str = ""  # set together with a password to authenticate
    # Password for smtp_user. Prefer the SMTP_PASSWORD_ENV env var over the
    # toml; the env value wins when both are set.
    smtp_password: str = ""


def _message_with_headers(recipient: str, subject: str, body: str) -> str:
    """An RFC-822-ish message for SMTP-style transports (msmtp/sendmail)."""
    return f"To: {recipient}\nSubject: {subject}\nFrom: streetscape-tracker@{socket.gethostname()}\n\n{body}\n"


def _default_smtp_from() -> str:
    """Sender used when [alerts] smtp_from is unset."""
    return f"streetscape-tracker@{socket.gethostname()}"


def build_smtp_message(sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    """
    Build the EmailMessage sent by the ``smtp`` transport.

    Side-effect-free (no network) so tests can assert the headers/body without
    a relay. ``sender`` empty falls back to ``streetscape-tracker@<hostname>``.
    """
    msg = EmailMessage()
    msg["From"] = sender or _default_smtp_from()
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


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


def _send_smtp(cfg: AlertConfig, subject: str, full_subject: str, body: str) -> bool:
    """
    Send via stdlib smtplib straight to a relay — no local mailer, so a
    hardened systemd sandbox can't break it (issue #144). Never raises.
    """
    if not cfg.smtp_host:
        logger.error('Alert not sent — transport "smtp" requires [alerts] smtp_host')
        return False
    password = os.environ.get(SMTP_PASSWORD_ENV) or cfg.smtp_password
    msg = build_smtp_message(cfg.smtp_from, cfg.recipient, full_subject, body)
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
            if cfg.smtp_starttls:
                smtp.starttls()
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        logger.error(f"Alert send failed (smtp {cfg.smtp_host}:{cfg.smtp_port}): {e}")
        return False
    logger.info(f"Alert emailed to {cfg.recipient} via smtp {cfg.smtp_host}: {subject}")
    return True


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

    if cfg.transport == "smtp":
        return _send_smtp(cfg, subject, full_subject, body)

    try:
        cmd, stdin_text, use_shell = build_send_plan(
            cfg.transport, cfg.recipient, full_subject, body, cfg.command
        )
    except ValueError as e:
        logger.error(f"Alert not sent — bad config: {e}")
        return False

    env = None
    if use_shell:
        env = {
            **os.environ,
            "STREETSCAPE_ALERT_SUBJECT": full_subject,
            "STREETSCAPE_ALERT_TO": cfg.recipient,
        }
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

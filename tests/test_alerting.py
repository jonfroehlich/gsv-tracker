"""
Alerting tests (issue #92): transport plan construction, threshold logic, and
the send path — exercised with harmless shell commands (`true`/`false`) so no
mail is ever sent. Also round-trips an [alerts] TOML section through the
scheduler config loader to confirm the wiring.
"""

import smtplib

import pytest

from streetscape_metadata_tracker.alerting import (
    SMTP_PASSWORD_ENV,
    AlertConfig,
    build_send_plan,
    build_smtp_message,
    send_alert,
    should_alert,
)


class TestBuildSendPlan:
    def test_mail(self):
        cmd, stdin, shell = build_send_plan("mail", "a@b.c", "subj", "hello")
        assert cmd == ["mail", "-s", "subj", "a@b.c"]
        assert stdin == "hello" and shell is False

    def test_msmtp_has_headers_and_recipient(self):
        cmd, stdin, shell = build_send_plan("msmtp", "a@b.c", "subj", "hi")
        assert cmd == ["msmtp", "a@b.c"] and shell is False
        assert "To: a@b.c" in stdin and "Subject: subj" in stdin
        assert stdin.endswith("hi\n")

    def test_sendmail_reads_recipient_from_headers(self):
        cmd, stdin, shell = build_send_plan("sendmail", "a@b.c", "s", "b")
        assert cmd == ["sendmail", "-t"] and "To: a@b.c" in stdin

    def test_command_is_shell(self):
        cmd, stdin, shell = build_send_plan("command", "", "s", "body", command="cat >/dev/null")
        assert cmd == "cat >/dev/null" and stdin == "body" and shell is True

    def test_command_without_command_raises(self):
        with pytest.raises(ValueError):
            build_send_plan("command", "a@b.c", "s", "b")

    def test_unknown_transport_raises(self):
        with pytest.raises(ValueError):
            build_send_plan("carrier-pigeon", "a@b.c", "s", "b")


class TestShouldAlert:
    @pytest.mark.parametrize(
        "failures,threshold,expected",
        [
            (0, 1, False),
            (1, 1, True),
            (2, 3, False),
            (3, 3, True),
            (5, 0, True),  # threshold floored at 1
        ],
    )
    def test_threshold(self, failures, threshold, expected):
        assert should_alert(failures, threshold) is expected


class TestSendAlert:
    def test_disabled_is_noop(self):
        assert send_alert(AlertConfig(enabled=False), "s", "b") is False

    def test_enabled_without_recipient_skips(self):
        # mail/msmtp need a recipient; missing one must not attempt a send
        cfg = AlertConfig(enabled=True, recipient="", transport="mail")
        assert send_alert(cfg, "s", "b") is False

    def test_command_success(self):
        cfg = AlertConfig(enabled=True, transport="command", command="true")
        assert send_alert(cfg, "s", "b") is True

    def test_command_failure_returns_false(self):
        cfg = AlertConfig(enabled=True, transport="command", command="false")
        assert send_alert(cfg, "s", "b") is False

    def test_command_receives_subject_and_recipient_in_env(self, tmp_path):
        out = tmp_path / "env.txt"
        cfg = AlertConfig(
            enabled=True,
            transport="command",
            recipient="x@y.z",
            subject_prefix="[p]",
            command=f'echo "$STREETSCAPE_ALERT_SUBJECT -> $STREETSCAPE_ALERT_TO" > {out}',
        )
        assert send_alert(cfg, "boom", "body") is True
        assert out.read_text().strip() == "[p] boom -> x@y.z"


class _FakeSMTP:
    """
    Stand-in for smtplib.SMTP that records what it was asked to do instead of
    touching the network. Supports the context-manager protocol send_alert uses.
    """

    def __init__(self, host, port, timeout=None, raise_on=None):
        self.host, self.port, self.timeout = host, port, timeout
        self._raise_on = raise_on or set()
        self.started_tls = False
        self.login_args = None
        self.sent = []
        if "connect" in self._raise_on:
            raise OSError("connection refused")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        if "login" in self._raise_on:
            raise smtplib.SMTPAuthenticationError(535, b"bad creds")
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


def _patch_smtp(monkeypatch, raise_on=None):
    """Patch alerting's smtplib.SMTP to a recording fake; return a captor list."""
    captured = []

    def factory(host, port, timeout=None):
        smtp = _FakeSMTP(host, port, timeout, raise_on=raise_on)
        captured.append(smtp)
        return smtp

    monkeypatch.setattr("streetscape_metadata_tracker.alerting.smtplib.SMTP", factory)
    return captured


class TestBuildSmtpMessage:
    def test_headers_and_body(self):
        msg = build_smtp_message("noreply@host", "a@b.c", "subj", "line one")
        assert msg["From"] == "noreply@host"
        assert msg["To"] == "a@b.c"
        assert msg["Subject"] == "subj"
        assert msg.get_content().strip() == "line one"

    def test_empty_sender_defaults_to_hostname(self):
        msg = build_smtp_message("", "a@b.c", "s", "b")
        assert msg["From"].startswith("streetscape-tracker@")


class TestSendAlertSmtp:
    def _cfg(self, **kw):
        base = dict(
            enabled=True,
            recipient="ops@example.edu",
            transport="smtp",
            smtp_host="relay.example.edu",
            subject_prefix="[p]",
        )
        base.update(kw)
        return AlertConfig(**base)

    def test_plain_relay_sends(self, monkeypatch):
        captured = _patch_smtp(monkeypatch)
        assert send_alert(self._cfg(smtp_port=2525), "boom", "body") is True
        (smtp,) = captured
        assert (smtp.host, smtp.port) == ("relay.example.edu", 2525)
        assert smtp.started_tls is False and smtp.login_args is None
        (msg,) = smtp.sent
        assert msg["To"] == "ops@example.edu"
        assert msg["Subject"] == "[p] boom"

    def test_missing_host_is_noop(self, monkeypatch):
        captured = _patch_smtp(monkeypatch)
        assert send_alert(self._cfg(smtp_host=""), "s", "b") is False
        assert captured == []

    def test_starttls_and_auth_when_configured(self, monkeypatch):
        captured = _patch_smtp(monkeypatch)
        cfg = self._cfg(smtp_starttls=True, smtp_user="u", smtp_password="pw")
        assert send_alert(cfg, "s", "b") is True
        (smtp,) = captured
        assert smtp.started_tls is True
        assert smtp.login_args == ("u", "pw")

    def test_password_env_overrides_toml(self, monkeypatch):
        captured = _patch_smtp(monkeypatch)
        monkeypatch.setenv(SMTP_PASSWORD_ENV, "from-env")
        cfg = self._cfg(smtp_user="u", smtp_password="from-toml")
        assert send_alert(cfg, "s", "b") is True
        assert captured[0].login_args == ("u", "from-env")

    def test_connect_failure_swallowed(self, monkeypatch):
        _patch_smtp(monkeypatch, raise_on={"connect"})
        assert send_alert(self._cfg(), "s", "b") is False

    def test_auth_failure_swallowed(self, monkeypatch):
        _patch_smtp(monkeypatch, raise_on={"login"})
        cfg = self._cfg(smtp_user="u", smtp_password="pw")
        assert send_alert(cfg, "s", "b") is False

    def test_smtp_still_requires_recipient(self, monkeypatch):
        captured = _patch_smtp(monkeypatch)
        assert send_alert(self._cfg(recipient=""), "s", "b") is False
        assert captured == []

    def test_bad_header_is_swallowed(self, monkeypatch):
        # A newline in the subject makes EmailMessage header assignment raise
        # ValueError; alerting must catch it, not crash the run.
        captured = _patch_smtp(monkeypatch)
        assert send_alert(self._cfg(), "line one\nInjected: header", "b") is False
        assert captured == []


def test_config_loader_reads_alerts_section(tmp_path):
    from streetscape_metadata_tracker.scheduler import load_scheduler_config

    p = tmp_path / "s.toml"
    p.write_text(
        "[alerts]\n"
        "enabled = true\n"
        'recipient = "ops@example.edu"\n'
        'transport = "smtp"\n'
        "failure_threshold = 3\n"
        'smtp_host = "relay.example.edu"\n'
        "smtp_port = 587\n"
        "smtp_starttls = true\n"
        'smtp_user = "svc"\n'
    )
    cfg = load_scheduler_config(str(p))
    assert cfg.alerts.enabled is True
    assert cfg.alerts.recipient == "ops@example.edu"
    assert cfg.alerts.transport == "smtp"
    assert cfg.alerts.failure_threshold == 3
    assert cfg.alerts.smtp_host == "relay.example.edu"
    assert cfg.alerts.smtp_port == 587
    assert cfg.alerts.smtp_starttls is True
    assert cfg.alerts.smtp_user == "svc"


def test_config_loader_alerts_default_off(tmp_path):
    from streetscape_metadata_tracker.scheduler import load_scheduler_config

    p = tmp_path / "s.toml"
    p.write_text("[schedule]\ncycle_days = 90\n")
    cfg = load_scheduler_config(str(p))
    assert cfg.alerts.enabled is False

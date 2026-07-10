"""
Alerting tests (issue #92): transport plan construction, threshold logic, and
the send path — exercised with harmless shell commands (`true`/`false`) so no
mail is ever sent. Also round-trips an [alerts] TOML section through the
scheduler config loader to confirm the wiring.
"""

import pytest

from streetscape_metadata_tracker.alerting import (
    AlertConfig,
    build_send_plan,
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


def test_config_loader_reads_alerts_section(tmp_path):
    from streetscape_metadata_tracker.scheduler import load_scheduler_config

    p = tmp_path / "s.toml"
    p.write_text(
        "[alerts]\n"
        "enabled = true\n"
        'recipient = "ops@example.edu"\n'
        'transport = "msmtp"\n'
        "failure_threshold = 3\n"
    )
    cfg = load_scheduler_config(str(p))
    assert cfg.alerts.enabled is True
    assert cfg.alerts.recipient == "ops@example.edu"
    assert cfg.alerts.transport == "msmtp"
    assert cfg.alerts.failure_threshold == 3


def test_config_loader_alerts_default_off(tmp_path):
    from streetscape_metadata_tracker.scheduler import load_scheduler_config

    p = tmp_path / "s.toml"
    p.write_text("[schedule]\ncycle_days = 90\n")
    cfg = load_scheduler_config(str(p))
    assert cfg.alerts.enabled is False

"""Scheduler logic tests — pure logic only, no network or subprocesses."""

import os
from datetime import date

from streetscape_metadata_tracker import db
from streetscape_metadata_tracker.scheduler import (
    ResourceGuardConfig,
    SchedulerConfig,
    SystemPressure,
    build_parser,
    estimate_requests,
    load_scheduler_config,
    plan_connection_limit,
)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _register(conn, name, width=5000, height=5000, step=20):
    return db.register_city(
        conn,
        city_name=name,
        state_name="Oregon",
        state_code="OR",
        country_name="United States",
        country_code="US",
        center_lat=44.0,
        center_lon=-121.0,
        grid_width_m=width,
        grid_height_m=height,
        step_m=step,
    )


def test_run_one_city_command_defers_skip_policy_to_scheduler(conn, monkeypatch):
    """
    The scheduler already decided this city is due (cycle − grace), so the
    subprocess must run with --min-days-since-last-run 0: otherwise any
    config with cycle_days − grace_days ≤ the CLI default (80) makes every
    run "succeed" as a skip — stamping last_success_at while never
    collecting anything. The city name must also follow '--' so a display
    name starting with '-' can't be parsed as a flag.
    """
    from streetscape_metadata_tracker import scheduler as sched

    cid = _register(conn, "Bend")
    city = db.resolve_city(conn, cid)

    captured = {}

    def fake_run(cmd, timeout=None, cwd=None):
        captured["cmd"] = cmd

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(sched.subprocess, "run", fake_run)
    assert sched._run_one_city(SchedulerConfig(), city, date(2026, 7, 1), "gsv")

    cmd = captured["cmd"]
    i = cmd.index("--min-days-since-last-run")
    assert cmd[i + 1] == "0"
    # Client-side quota pacing must reach every subprocess.
    i = cmd.index("--max-requests-per-minute")
    assert cmd[i + 1] == "24000"
    assert cmd[cmd.index("--") + 1] == city.display_name
    assert cmd[-1] == city.display_name


def test_estimate_requests_matches_grid_math(conn):
    cid = _register(conn, "Bend", width=1000, height=1000, step=20)
    city = db.resolve_city(conn, cid)
    assert estimate_requests(city) == 51 * 51  # (1000//20 + 1)^2


def test_estimate_requests_mapillary_counts_tiles(conn):
    cid = _register(conn, "Bend", width=5000, height=5000, step=20)
    city = db.resolve_city(conn, cid)
    tiles = estimate_requests(city, provider="mapillary")
    # A 5km grid is a handful of z14 tiles — three orders of magnitude
    # cheaper than GSV's per-point requests
    assert 4 <= tiles <= 25
    assert tiles < estimate_requests(city) / 100


def test_city_timeout_scales_with_grid_size(conn):
    """A huge GSV grid gets a timeout derived from points ÷ rate (so it is not
    SIGKILLed mid-run by the flat floor); a small city keeps the floor."""
    from streetscape_metadata_tracker.scheduler import city_timeout_seconds

    cfg = SchedulerConfig(city_timeout_minutes=180, max_requests_per_minute=24_000)
    floor = 180 * 60

    small = db.resolve_city(conn, _register(conn, "Bend", width=1000, height=1000, step=20))
    assert city_timeout_seconds(cfg, small, "gsv") == floor  # 2601 pts, well under floor

    big = db.resolve_city(conn, _register(conn, "Metropolis", width=40000, height=40000, step=20))
    # ~4M points at 24k/min ≈ 167 min of paced requests; with headroom this
    # must exceed the flat floor rather than clamp to it.
    assert city_timeout_seconds(cfg, big, "gsv") > floor


def test_city_timeout_floor_for_mapillary_and_disabled_pacing(conn):
    from streetscape_metadata_tracker.scheduler import city_timeout_seconds

    big = db.resolve_city(conn, _register(conn, "Metropolis", width=40000, height=40000, step=20))
    floor = 180 * 60
    # Mapillary is fast bulk metadata — keep the flat floor regardless of grid.
    assert city_timeout_seconds(SchedulerConfig(), big, "mapillary") == floor
    # No client-side pacing -> no basis to scale, keep the floor.
    assert city_timeout_seconds(SchedulerConfig(max_requests_per_minute=0), big, "gsv") == floor


def test_config_defaults_when_file_missing(tmp_path):
    cfg = load_scheduler_config(str(tmp_path / "nope.toml"))
    assert cfg.cycle_days == 90 and cfg.batch_size == 100
    assert cfg.max_requests_per_minute == 24_000
    assert cfg.db_path.endswith("streetscape_tracker.db")
    # No [providers] config → gsv-only with the legacy budget
    assert cfg.enabled_providers() == ["gsv"]
    assert cfg.providers["gsv"].daily_request_budget == 10_000_000


def test_config_parses_toml(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text("""
[schedule]
cycle_days = 30
daily_request_budget = 1000
[download]
batch_size = 7
max_requests_per_minute = 48000
[publish]
enabled = true
""")
    cfg = load_scheduler_config(str(p))
    assert cfg.cycle_days == 30
    assert cfg.daily_request_budget == 1000
    assert cfg.batch_size == 7
    assert cfg.max_requests_per_minute == 48000
    assert cfg.publish_enabled
    # v1-style toml (no [providers]): gsv-only, legacy budget honored
    assert cfg.enabled_providers() == ["gsv"]
    assert cfg.providers["gsv"].daily_request_budget == 1000


def test_config_parses_provider_sections(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text("""
[schedule]
cycle_days = 30
[providers.gsv]
daily_request_budget = 99000
[providers.mapillary]
enabled = true
daily_request_budget = 5000
[providers.bogus]
daily_request_budget = 1
""")
    cfg = load_scheduler_config(str(p))
    assert cfg.enabled_providers() == ["gsv", "mapillary"]  # gsv always first
    assert cfg.providers["gsv"].daily_request_budget == 99_000
    assert cfg.providers["mapillary"].daily_request_budget == 5000
    assert "bogus" not in cfg.providers  # unknown providers are ignored


def test_config_provider_can_be_disabled(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text("""
[providers.gsv]
daily_request_budget = 99000
[providers.mapillary]
enabled = false
""")
    cfg = load_scheduler_config(str(p))
    assert cfg.enabled_providers() == ["gsv"]


def test_config_flag_accepted_on_either_side_of_subcommand():
    # --config is global; a prior systemd unit put it AFTER the subcommand, which
    # argparse rejected and would have failed the nightly service. It must now
    # parse on both sides. See build_parser / _add_global_flags.
    parser = build_parser()

    before = parser.parse_args(["--config", "/x.toml", "run-due", "--dry-run"])
    assert before.command == "run-due" and before.config == "/x.toml" and before.dry_run

    after = parser.parse_args(["run-due", "--config", "/x.toml", "--dry-run"])
    assert after.command == "run-due" and after.config == "/x.toml" and after.dry_run

    # Works for a plain subcommand after the flag too.
    assert parser.parse_args(["--config", "/y.toml", "status"]).config == "/y.toml"

    # Omitted entirely: SUPPRESS leaves the attr absent so main() falls back to None.
    assert getattr(parser.parse_args(["status"]), "config", None) is None


def test_regenerate_aggregate_parses_publish_flag():
    parser = build_parser()
    a = parser.parse_args(["regenerate-aggregate"])
    assert a.command == "regenerate-aggregate" and a.publish is False
    b = parser.parse_args(["--config", "/x.toml", "regenerate-aggregate", "--publish"])
    assert b.command == "regenerate-aggregate" and b.publish and b.config == "/x.toml"


def test_regenerate_aggregate_rebuilds_without_publish(conn, monkeypatch):
    """regenerate-aggregate rebuilds the aggregate and, without --publish,
    never touches the publish script."""
    from streetscape_metadata_tracker import scheduler as sched

    calls = {"agg": 0, "publish": 0}
    monkeypatch.setattr(sched.db, "connect", lambda path: conn)
    monkeypatch.setattr(
        sched,
        "generate_aggregate_v2",
        lambda c, d: calls.__setitem__("agg", calls["agg"] + 1) or {"cities_count": 3},
    )
    monkeypatch.setattr(sched, "_publish", lambda cfg, ctx: calls.__setitem__("publish", 1) or 0)

    rc = sched.cmd_regenerate(SchedulerConfig(publish_enabled=False))
    assert rc == 0 and calls == {"agg": 1, "publish": 0}


def test_regenerate_aggregate_publishes_on_flag(conn, monkeypatch):
    """--publish runs the publish step even when [publish].enabled is false,
    and a publish failure surfaces as a nonzero exit."""
    from streetscape_metadata_tracker import scheduler as sched

    monkeypatch.setattr(sched.db, "connect", lambda path: conn)
    monkeypatch.setattr(sched, "generate_aggregate_v2", lambda c, d: {"cities_count": 0})

    published = []
    monkeypatch.setattr(sched, "_publish", lambda cfg, ctx: published.append(ctx) or 0)
    assert sched.cmd_regenerate(SchedulerConfig(publish_enabled=False), publish=True) == 0
    assert published  # publish ran despite publish_enabled=False

    monkeypatch.setattr(sched, "_publish", lambda cfg, ctx: 1)  # simulate rsync failure
    assert sched.cmd_regenerate(SchedulerConfig(publish_enabled=False), publish=True) == 1


def test_makelab1_production_config_is_wired():
    # Guard the checked-in production config the systemd unit points at.
    cfg = load_scheduler_config(os.path.join(_PROJECT_ROOT, "config", "scheduler.makelab1.toml"))
    assert cfg.enabled_providers() == ["gsv", "mapillary"]
    assert cfg.publish_enabled
    assert cfg.publish_script.endswith("sync_data_to_server.sh")
    assert cfg.alerts.enabled and cfg.alerts.transport == "mail" and cfg.alerts.recipient
    # Data/DB live on lab storage (makelab2), not in the web docroot.
    assert "/projects/makeabilitylab/streetscape-tracker" in cfg.db_path
    assert "/cse/web/" not in cfg.db_path and "/cse/web/" not in cfg.data_dir
    # Shared-host resource guard is active in production.
    assert cfg.resource_guard.enabled


def test_run_one_city_honors_connection_limit_override(conn, monkeypatch):
    """The resource guard lowers concurrency by passing a connection_limit
    override, which must reach the subprocess as --connection-limit."""
    from streetscape_metadata_tracker import scheduler as sched

    cid = _register(conn, "Bend")
    city = db.resolve_city(conn, cid)
    captured = {}

    def fake_run(cmd, timeout=None, cwd=None):
        captured["cmd"] = cmd

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(sched.subprocess, "run", fake_run)
    assert sched._run_one_city(SchedulerConfig(), city, date(2026, 7, 1), "gsv", connection_limit=7)
    cmd = captured["cmd"]
    assert cmd[cmd.index("--connection-limit") + 1] == "7"


def test_plan_connection_limit_no_pressure_keeps_base():
    # No /proc data (non-Linux, read failure) → never throttle.
    assert plan_connection_limit(50, None, ResourceGuardConfig()) == (50, None)


def test_plan_connection_limit_disabled_is_noop():
    cfg = ResourceGuardConfig(enabled=False)
    starved = SystemPressure(load5=999.0, ncpu=8, mem_available_gb=0.1)
    assert plan_connection_limit(50, starved, cfg) == (50, None)


def test_plan_connection_limit_healthy_box_keeps_base():
    cfg = ResourceGuardConfig()
    healthy = SystemPressure(load5=1.0, ncpu=48, mem_available_gb=100.0)
    assert plan_connection_limit(50, healthy, cfg) == (50, None)


def test_plan_connection_limit_low_memory_drops_to_floor():
    cfg = ResourceGuardConfig(min_available_memory_gb=8.0, min_connection_limit=5)
    tight = SystemPressure(load5=0.0, ncpu=48, mem_available_gb=2.0)
    limit, reason = plan_connection_limit(50, tight, cfg)
    assert limit == 5
    assert "low memory" in reason


def test_plan_connection_limit_high_load_scales_proportionally():
    # ceiling = 0.9 * 10 = 9; load 18 is 2× over → half the base.
    cfg = ResourceGuardConfig(max_load_per_core=0.9, min_connection_limit=5)
    busy = SystemPressure(load5=18.0, ncpu=10, mem_available_gb=64.0)
    limit, reason = plan_connection_limit(50, busy, cfg)
    assert limit == 25  # int(50 * 9 / 18)
    assert "high load" in reason


def test_plan_connection_limit_never_below_floor():
    cfg = ResourceGuardConfig(min_connection_limit=5)
    extreme = SystemPressure(load5=10_000.0, ncpu=8, mem_available_gb=100.0)
    limit, _ = plan_connection_limit(50, extreme, cfg)
    assert limit == 5


def test_read_system_pressure_returns_none_when_proc_unavailable(monkeypatch):
    import builtins

    from streetscape_metadata_tracker import scheduler as sched

    def boom(*a, **k):
        raise OSError("no /proc here")

    monkeypatch.setattr(builtins, "open", boom)
    assert sched.read_system_pressure() is None


def test_config_parses_resource_guard(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text(
        "[resource_guard]\n"
        "enabled = true\n"
        "min_available_memory_gb = 12.0\n"
        "max_load_per_core = 0.5\n"
        "min_connection_limit = 3\n"
    )
    cfg = load_scheduler_config(str(p))
    assert cfg.resource_guard.enabled
    assert cfg.resource_guard.min_available_memory_gb == 12.0
    assert cfg.resource_guard.max_load_per_core == 0.5
    assert cfg.resource_guard.min_connection_limit == 3


def test_config_resource_guard_defaults_on(tmp_path):
    cfg = load_scheduler_config(str(tmp_path / "nope.toml"))
    assert cfg.resource_guard.enabled is True
    assert cfg.resource_guard.min_connection_limit == 5


def test_due_cities_stalest_first(conn):
    a = _register(conn, "Alpha")
    b = _register(conn, "Beta")
    c = _register(conn, "Gamma")
    db.assign_schedule(conn, 90)

    # Beta succeeded long ago; Gamma succeeded recently; Alpha never ran
    conn.execute(
        "UPDATE schedule_state SET last_success_at = '2025-01-01T00:00:00+00:00' WHERE city_id = ?",
        (b,),
    )
    conn.execute(
        "UPDATE schedule_state SET last_success_at = '2026-06-30T00:00:00+00:00' WHERE city_id = ?",
        (c,),
    )
    conn.commit()

    due = db.get_due_cities(
        conn, today=date(2026, 7, 2), cycle_days=90, grace_days=7, max_consecutive_failures=5
    )
    ids = [x.city_id for x in due]
    assert ids[0] == a  # never-run first (NULL last_success)
    assert ids[1] == b  # then stalest
    assert c not in ids  # fresh city not due


def test_disabled_city_never_due(conn):
    cid = _register(conn, "Alpha")
    db.assign_schedule(conn, 90)
    conn.execute("UPDATE cities SET enabled = 0 WHERE city_id = ?", (cid,))
    conn.commit()
    due = db.get_due_cities(
        conn, today=date(2026, 7, 2), cycle_days=90, grace_days=7, max_consecutive_failures=5
    )
    assert due == []


def test_failure_cap_excludes_city(conn):
    cid = _register(conn, "Alpha")
    db.assign_schedule(conn, 90)
    for _ in range(5):
        db.record_attempt(conn, cid, success=False, error="x")
    due = db.get_due_cities(
        conn, today=date(2026, 7, 2), cycle_days=90, grace_days=7, max_consecutive_failures=5
    )
    assert due == []


def test_budget_ledger_defers_second_city_when_first_consumes_budget(conn, monkeypatch):
    """The remaining-budget check reads the LIVE api_usage ledger: after city
    A's run records its requests, city B (same size) no longer fits today and
    is deferred — not run over budget, and not marked as a failure."""
    from streetscape_metadata_tracker import scheduler as sched

    today = date(2026, 7, 2)
    # Each 1000x1000/20 city estimates (50+1)^2 = 2601 requests; a 4000
    # budget fits one such run but not two.
    a = _register(conn, "Alpha", width=1000, height=1000, step=20)
    b = _register(conn, "Beta", width=1000, height=1000, step=20)
    db.assign_schedule(conn, 90)
    conn.execute("UPDATE schedule_state SET last_success_at = NULL")  # both due
    conn.commit()

    ran = []

    def fake_run(cfg, city, run_today, provider="gsv", connection_limit=None):
        # Simulate the real pipeline's ledger write for the requests spent
        db.add_api_usage(conn, run_today, sched.estimate_requests(city, provider), provider)
        ran.append(city.city_id)
        return True

    monkeypatch.setattr(sched, "_run_one_city", fake_run)
    monkeypatch.setattr(sched.db, "connect", lambda path: conn)
    monkeypatch.setattr(sched.time, "sleep", lambda s: None)
    monkeypatch.setattr(sched, "generate_aggregate_v2", lambda c, d: None)

    cfg = SchedulerConfig(daily_request_budget=4_000, publish_enabled=False)
    rc = sched.cmd_run_due(cfg, today=today)

    assert len(ran) == 1  # exactly one city fit the budget
    assert rc == 0  # a budget deferral is not a failure
    assert db.get_api_usage(conn, today, "gsv") == 2601  # B never spent requests
    # The deferred city is untouched: still due tomorrow, no failure recorded
    deferred = b if ran == [a] else a
    row = conn.execute(
        "SELECT consecutive_failures, last_success_at FROM schedule_state "
        "WHERE city_id = ? AND provider = 'gsv'",
        (deferred,),
    ).fetchone()
    assert row["consecutive_failures"] == 0
    assert row["last_success_at"] is None


def test_oversized_city_does_not_starve_queue(conn, monkeypatch):
    """A city whose estimate exceeds the entire daily budget must be
    skipped (not break the loop), so smaller cities behind it still run.
    Regression: 82 real cities have grids too large for any daily budget;
    stalest-first ordering would otherwise block collection forever."""
    from streetscape_metadata_tracker import scheduler as sched

    huge = _register(conn, "Huge", width=200_000, height=200_000, step=20)
    small = _register(conn, "Small", width=1000, height=1000, step=20)
    db.assign_schedule(conn, 90)
    # Make Huge the stalest (never run) — both are due
    conn.execute("UPDATE schedule_state SET last_success_at = NULL")
    conn.commit()

    ran = []
    monkeypatch.setattr(
        sched,
        "_run_one_city",
        lambda cfg, city, today, provider="gsv", connection_limit=None: ran.append(city.city_id) or True,
    )
    monkeypatch.setattr(sched.db, "connect", lambda path: conn)
    monkeypatch.setattr(sched.time, "sleep", lambda s: None)
    monkeypatch.setattr(sched, "generate_aggregate_v2", lambda c, d: None)

    cfg = SchedulerConfig(daily_request_budget=10_000, publish_enabled=False)
    rc = sched.cmd_run_due(cfg, today=date(2026, 7, 2))

    assert huge not in ran  # skipped: never fits any budget
    assert small in ran  # not starved by the huge city ahead of it
    assert rc == 0


def test_run_due_pairs_providers_per_city(conn, monkeypatch):
    """A city due for both providers runs both back-to-back with the same
    run date, each within its own budget ledger and failure tracking."""
    from streetscape_metadata_tracker import scheduler as sched
    from streetscape_metadata_tracker.scheduler import ProviderConfig

    cid = _register(conn, "Bend", width=1000, height=1000, step=20)

    ran = []
    monkeypatch.setattr(
        sched,
        "_run_one_city",
        lambda cfg, city, today, provider="gsv", connection_limit=None: (
            ran.append((city.city_id, provider)) or (provider == "gsv")
        ),
    )
    monkeypatch.setattr(sched.db, "connect", lambda path: conn)
    monkeypatch.setattr(sched.time, "sleep", lambda s: None)
    monkeypatch.setattr(sched, "generate_aggregate_v2", lambda c, d: None)

    cfg = SchedulerConfig(
        publish_enabled=False,
        providers={
            "gsv": ProviderConfig(daily_request_budget=10_000),
            "mapillary": ProviderConfig(daily_request_budget=1_000),
        },
    )
    rc = sched.cmd_run_due(cfg, today=date(2026, 7, 2))

    assert ran == [(cid, "gsv"), (cid, "mapillary")]  # paired, gsv first
    assert rc == 1  # the (simulated) mapillary failure surfaces in the exit code

    # Success/failure recorded independently per provider
    rows = {
        r["provider"]: r
        for r in conn.execute(
            "SELECT provider, last_success_at, consecutive_failures "
            "FROM schedule_state WHERE city_id = ?",
            (cid,),
        )
    }
    assert rows["gsv"]["last_success_at"] is not None
    assert rows["gsv"]["consecutive_failures"] == 0
    assert rows["mapillary"]["last_success_at"] is None
    assert rows["mapillary"]["consecutive_failures"] == 1


def test_run_due_provider_budgets_are_independent(conn, monkeypatch):
    """Exhausting one provider's budget must not block the other."""
    from streetscape_metadata_tracker import scheduler as sched
    from streetscape_metadata_tracker.scheduler import ProviderConfig

    cid = _register(conn, "Bend", width=1000, height=1000, step=20)
    today = date(2026, 7, 2)  # pinned; must match the cmd_run_due call below
    # gsv's ledger is already full for today; mapillary's is untouched
    db.add_api_usage(conn, today, 10_000, provider="gsv")

    ran = []
    monkeypatch.setattr(
        sched,
        "_run_one_city",
        lambda cfg, city, today, provider="gsv", connection_limit=None: ran.append((city.city_id, provider)) or True,
    )
    monkeypatch.setattr(sched.db, "connect", lambda path: conn)
    monkeypatch.setattr(sched.time, "sleep", lambda s: None)
    monkeypatch.setattr(sched, "generate_aggregate_v2", lambda c, d: None)

    cfg = SchedulerConfig(
        publish_enabled=False,
        providers={
            "gsv": ProviderConfig(daily_request_budget=10_000),
            "mapillary": ProviderConfig(daily_request_budget=1_000),
        },
    )
    sched.cmd_run_due(cfg, today=date(2026, 7, 2))

    assert ran == [(cid, "mapillary")]  # gsv deferred, mapillary still ran

"""Scheduler logic tests — pure logic only, no network or subprocesses."""

from datetime import date

from gsv_metadata_tracker import db
from gsv_metadata_tracker.scheduler import (
    SchedulerConfig, estimate_requests, load_scheduler_config)


def _register(conn, name, width=5000, height=5000, step=20):
    return db.register_city(
        conn, city_name=name, state_name='Oregon', state_code='OR',
        country_name='United States', country_code='US',
        center_lat=44.0, center_lon=-121.0,
        grid_width_m=width, grid_height_m=height, step_m=step)


def test_estimate_requests_matches_grid_math(conn):
    cid = _register(conn, 'Bend', width=1000, height=1000, step=20)
    city = db.resolve_city(conn, cid)
    assert estimate_requests(city) == 51 * 51  # (1000//20 + 1)^2


def test_config_defaults_when_file_missing(tmp_path):
    cfg = load_scheduler_config(str(tmp_path / "nope.toml"))
    assert cfg.cycle_days == 90 and cfg.batch_size == 100
    assert cfg.db_path.endswith("gsv_tracker.db")


def test_config_parses_toml(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text("""
[schedule]
cycle_days = 30
daily_request_budget = 1000
[download]
batch_size = 7
[publish]
enabled = true
""")
    cfg = load_scheduler_config(str(p))
    assert cfg.cycle_days == 30
    assert cfg.daily_request_budget == 1000
    assert cfg.batch_size == 7
    assert cfg.publish_enabled


def test_due_cities_stalest_first(conn):
    a = _register(conn, 'Alpha')
    b = _register(conn, 'Beta')
    c = _register(conn, 'Gamma')
    db.assign_schedule(conn, 90)

    # Beta succeeded long ago; Gamma succeeded recently; Alpha never ran
    conn.execute("UPDATE schedule_state SET last_success_at = '2025-01-01T00:00:00+00:00' "
                 "WHERE city_id = ?", (b,))
    conn.execute("UPDATE schedule_state SET last_success_at = '2026-06-30T00:00:00+00:00' "
                 "WHERE city_id = ?", (c,))
    conn.commit()

    due = db.get_due_cities(conn, today=date(2026, 7, 2), cycle_days=90,
                            grace_days=7, max_consecutive_failures=5)
    ids = [x.city_id for x in due]
    assert ids[0] == a          # never-run first (NULL last_success)
    assert ids[1] == b          # then stalest
    assert c not in ids         # fresh city not due


def test_disabled_city_never_due(conn):
    cid = _register(conn, 'Alpha')
    db.assign_schedule(conn, 90)
    conn.execute("UPDATE cities SET enabled = 0 WHERE city_id = ?", (cid,))
    conn.commit()
    due = db.get_due_cities(conn, today=date(2026, 7, 2), cycle_days=90,
                            grace_days=7, max_consecutive_failures=5)
    assert due == []


def test_failure_cap_excludes_city(conn):
    cid = _register(conn, 'Alpha')
    db.assign_schedule(conn, 90)
    for _ in range(5):
        db.record_attempt(conn, cid, success=False, error='x')
    due = db.get_due_cities(conn, today=date(2026, 7, 2), cycle_days=90,
                            grace_days=7, max_consecutive_failures=5)
    assert due == []


def test_budget_math():
    cfg = SchedulerConfig(daily_request_budget=10_000)
    # A 2000x2000/20 city needs 101*101 = 10201 requests > budget
    assert (2000 // 20 + 1) ** 2 > cfg.daily_request_budget

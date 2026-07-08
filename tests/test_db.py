"""Catalog tests: registration, aliases, runs, diffs, budget, scheduling."""

import sqlite3
from datetime import date

import pytest

from gsv_metadata_tracker import db


@pytest.fixture
def city(conn):
    return db.register_city(
        conn, city_name='Bend', state_name='Oregon', state_code='OR',
        country_name='United States', country_code='US',
        center_lat=44.05, center_lon=-121.31,
        grid_width_m=5000, grid_height_m=5000, step_m=20)


def test_register_city_derives_canonical_id(conn, city):
    assert city == 'bend--oregon--united-states'
    row = db.resolve_city(conn, 'Bend, Oregon, United States')
    assert row.grid_width_m == 5000 and row.enabled


def test_register_city_is_idempotent_and_freezes_geometry(conn, city):
    again = db.register_city(
        conn, city_name='Bend', state_name='Oregon', state_code='OR',
        country_name='United States', country_code='US',
        center_lat=99.9, center_lon=99.9,          # different geometry...
        grid_width_m=1, grid_height_m=1, step_m=1)
    assert again == city
    row = db.resolve_city(conn, city)
    assert row.center_lat == 44.05 and row.grid_width_m == 5000  # ...must not overwrite


def test_alias_resolution(conn, city):
    db.add_alias(conn, 'bend--or', city)
    assert db.resolve_city(conn, 'Bend, OR').city_id == city
    assert db.resolve_city(conn, 'Nowhere, KS') is None


def test_update_city_geometry_overwrites_and_appends_note(conn, city):
    db.update_city_geometry(
        conn, city_id=city, center_lat=44.10, center_lon=-121.40,
        grid_width_m=18000, grid_height_m=20000, notes='regeom #91')
    row = db.resolve_city(conn, city)
    assert (row.center_lat, row.center_lon) == (44.10, -121.40)
    assert row.grid_width_m == 18000 and row.grid_height_m == 20000
    assert row.step_m == 20                       # step is untouched
    assert row.notes == 'regeom #91'
    # A second correction appends to (does not clobber) the audit-trail note.
    db.update_city_geometry(
        conn, city_id=city, center_lat=44.11, center_lon=-121.41,
        grid_width_m=18000, grid_height_m=20000, notes='regeom #91 again')
    assert db.resolve_city(conn, city).notes == 'regeom #91\nregeom #91 again'


def test_update_city_geometry_unknown_city_raises(conn):
    with pytest.raises(KeyError):
        db.update_city_geometry(
            conn, city_id='nope', center_lat=1.0, center_lon=2.0,
            grid_width_m=100, grid_height_m=100)


def test_runs_ordering_and_uniqueness(conn, city):
    r1 = db.register_run(conn, city_id=city, run_date=date(2026, 4, 1),
                         csv_filename='a.csv.gz')
    r2 = db.register_run(conn, city_id=city, run_date=date(2026, 7, 1),
                         csv_filename='b.csv.gz')
    assert db.get_latest_run(conn, city).run_id == r2
    assert db.get_previous_run(conn, city, date(2026, 7, 1)).run_id == r1
    assert [r.run_id for r in db.get_runs_for_city(conn, city)] == [r1, r2]
    with pytest.raises(sqlite3.IntegrityError):  # same city+date rejected
        db.register_run(conn, city_id=city, run_date=date(2026, 7, 1),
                        csv_filename='c.csv.gz')


def test_diff_storage(conn, city):
    r1 = db.register_run(conn, city_id=city, run_date=date(2026, 4, 1),
                         csv_filename='a.csv.gz')
    r2 = db.register_run(conn, city_id=city, run_date=date(2026, 7, 1),
                         csv_filename='b.csv.gz')
    db.record_diff(conn, city_id=city, from_run_id=r1, to_run_id=r2,
                   grid_aligned=True, panos_added=5, panos_removed=2,
                   panos_persisted=93, capture_date_changed=1,
                   points_gained_coverage=3, points_lost_coverage=1,
                   coverage_delta_pct=0.5, detail_filename='d.csv.gz')
    row = db.get_diff_for_run(conn, r2)
    assert row['panos_added'] == 5 and row['grid_aligned'] == 1


def test_api_usage_ledger(conn):
    d = date(2026, 7, 1)
    assert db.get_api_usage(conn, d) == 0
    db.add_api_usage(conn, d, 100)
    db.add_api_usage(conn, d, 50)
    assert db.get_api_usage(conn, d) == 150


def test_due_selection_lifecycle(conn, city):
    kw = dict(today=date(2026, 7, 2), cycle_days=90, grace_days=7,
              max_consecutive_failures=5)
    db.assign_schedule(conn, 90)
    assert [c.city_id for c in db.get_due_cities(conn, **kw)] == [city]  # never run

    db.record_attempt(conn, city, success=True)
    assert db.get_due_cities(conn, **kw) == []  # fresh

    # Failure cap: repeated failures eventually remove the city from `due`
    for _ in range(5):
        db.record_attempt(conn, city, success=False, error='boom')
    row = conn.execute("SELECT consecutive_failures, last_error FROM schedule_state "
                       "WHERE city_id = ?", (city,)).fetchone()
    assert row['consecutive_failures'] == 5 and row['last_error'] == 'boom'


def test_stagger_is_stable_and_spread():
    days = [db.compute_day_of_cycle(f'city-{i}', 90) for i in range(900)]
    assert days == [db.compute_day_of_cycle(f'city-{i}', 90) for i in range(900)]
    assert len(set(days)) == 90  # every day of the cycle gets cities


# ── Provider dimension (schema v2) ─────────────────────────────────────────

def test_runs_per_provider_series(conn, city):
    g1 = db.register_run(conn, city_id=city, run_date=date(2026, 4, 1),
                         csv_filename='g1.csv.gz')
    m1 = db.register_run(conn, city_id=city, run_date=date(2026, 4, 1),
                         csv_filename='m1.csv.gz', provider='mapillary')
    m2 = db.register_run(conn, city_id=city, run_date=date(2026, 7, 1),
                         csv_filename='m2.csv.gz', provider='mapillary')
    # Same city+date is fine across providers, rejected within one
    with pytest.raises(sqlite3.IntegrityError):
        db.register_run(conn, city_id=city, run_date=date(2026, 4, 1),
                        csv_filename='m1b.csv.gz', provider='mapillary')
    # Lookups are per-provider series
    assert db.get_latest_run(conn, city).run_id == g1
    assert db.get_latest_run(conn, city, provider='mapillary').run_id == m2
    assert db.get_previous_run(conn, city, date(2026, 7, 1),
                               provider='mapillary').run_id == m1
    # gsv series is independent: nothing before its own first run
    assert db.get_previous_run(conn, city, date(2026, 4, 1)) is None
    assert [r.run_id for r in db.get_runs_for_city(conn, city)] == [g1]
    assert [r.run_id for r in
            db.get_runs_for_city(conn, city, provider='mapillary')] == [m1, m2]
    assert [r.run_id for r in
            db.get_runs_for_city(conn, city, provider=None)] == [g1, m1, m2]


def test_api_usage_ledger_per_provider(conn):
    d = date(2026, 7, 1)
    db.add_api_usage(conn, d, 100)
    db.add_api_usage(conn, d, 30, provider='mapillary')
    db.add_api_usage(conn, d, 30, provider='mapillary')
    assert db.get_api_usage(conn, d) == 100
    assert db.get_api_usage(conn, d, provider='mapillary') == 60


def test_schedule_state_per_provider(conn, city):
    kw = dict(today=date(2026, 7, 2), cycle_days=90, grace_days=7,
              max_consecutive_failures=5)
    db.assign_schedule(conn, 90, providers=('gsv', 'mapillary'))
    # Both providers land on the same cycle day (paired snapshots)
    days = conn.execute(
        "SELECT DISTINCT day_of_cycle FROM schedule_state WHERE city_id = ?",
        (city,)).fetchall()
    assert len(days) == 1

    # A gsv success leaves the city due for mapillary, and vice versa
    db.record_attempt(conn, city, success=True)
    assert db.get_due_cities(conn, **kw) == []
    assert [c.city_id for c in
            db.get_due_cities(conn, provider='mapillary', **kw)] == [city]

    # Failures accrue per provider
    for _ in range(5):
        db.record_attempt(conn, city, success=False, error='boom',
                          provider='mapillary')
    assert db.get_due_cities(conn, provider='mapillary', **kw) == []
    row = conn.execute(
        "SELECT consecutive_failures FROM schedule_state "
        "WHERE city_id = ? AND provider = 'gsv'", (city,)).fetchone()
    assert row['consecutive_failures'] == 0


# The v1 schema verbatim (pre-provider), for migration testing.
_V1_SCHEMA = """
CREATE TABLE cities (
    city_id        TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL,
    city_name      TEXT NOT NULL,
    state_name     TEXT,
    state_code     TEXT,
    country_name   TEXT,
    country_code   TEXT,
    center_lat     REAL NOT NULL,
    center_lon     REAL NOT NULL,
    grid_width_m   INTEGER NOT NULL,
    grid_height_m  INTEGER NOT NULL,
    step_m         INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    enabled        INTEGER NOT NULL DEFAULT 1,
    notes          TEXT
);
CREATE TABLE city_aliases (
    alias_slug     TEXT PRIMARY KEY,
    city_id        TEXT NOT NULL REFERENCES cities(city_id)
);
CREATE TABLE runs (
    run_id              INTEGER PRIMARY KEY,
    city_id             TEXT NOT NULL REFERENCES cities(city_id),
    run_date            TEXT NOT NULL,
    csv_filename        TEXT NOT NULL UNIQUE,
    json_filename       TEXT,
    is_baseline         INTEGER NOT NULL DEFAULT 0,
    started_at          TEXT,
    finished_at         TEXT,
    duration_seconds    REAL,
    total_points        INTEGER,
    status_ok           INTEGER,
    status_zero_results INTEGER,
    status_other        INTEGER,
    unique_panos        INTEGER,
    unique_google_panos INTEGER,
    coverage_rate_pct   REAL,
    oldest_capture_date TEXT,
    newest_capture_date TEXT,
    median_pano_age_years REAL,
    api_requests        INTEGER,
    UNIQUE (city_id, run_date)
);
CREATE INDEX idx_runs_city_date ON runs(city_id, run_date DESC);
CREATE TABLE run_diffs (
    diff_id                INTEGER PRIMARY KEY,
    city_id                TEXT NOT NULL REFERENCES cities(city_id),
    from_run_id            INTEGER NOT NULL REFERENCES runs(run_id),
    to_run_id              INTEGER NOT NULL REFERENCES runs(run_id),
    grid_aligned           INTEGER NOT NULL,
    panos_added            INTEGER,
    panos_removed          INTEGER,
    panos_persisted        INTEGER,
    capture_date_changed   INTEGER,
    points_gained_coverage INTEGER,
    points_lost_coverage   INTEGER,
    coverage_delta_pct     REAL,
    detail_filename        TEXT,
    computed_at            TEXT NOT NULL,
    UNIQUE (from_run_id, to_run_id)
);
CREATE TABLE api_usage (
    usage_date  TEXT PRIMARY KEY,
    requests    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE schedule_state (
    city_id              TEXT PRIMARY KEY REFERENCES cities(city_id),
    day_of_cycle         INTEGER NOT NULL,
    last_attempt_at      TEXT,
    last_success_at      TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error           TEXT
);
"""


def test_migrate_v1_to_v2(tmp_path):
    db_path = str(tmp_path / 'v1.db')
    raw = sqlite3.connect(db_path)
    raw.executescript(_V1_SCHEMA)
    raw.execute(
        """INSERT INTO cities (city_id, display_name, city_name, center_lat,
           center_lon, grid_width_m, grid_height_m, step_m, created_at)
           VALUES ('bend--or', 'Bend, OR', 'Bend', 44.05, -121.31,
                   5000, 5000, 20, '2026-01-01T00:00:00+00:00')""")
    raw.execute(
        """INSERT INTO runs (run_id, city_id, run_date, csv_filename,
           unique_panos, unique_google_panos)
           VALUES (7, 'bend--or', '2026-04-01', 'a.csv.gz', 100, 90)""")
    raw.execute(
        """INSERT INTO run_diffs (city_id, from_run_id, to_run_id,
           grid_aligned, computed_at)
           VALUES ('bend--or', 7, 7, 1, '2026-04-01T00:00:00+00:00')""")
    raw.execute("INSERT INTO api_usage VALUES ('2026-04-01', 12345)")
    raw.execute(
        """INSERT INTO schedule_state (city_id, day_of_cycle, last_success_at)
           VALUES ('bend--or', 42, '2026-04-01T00:00:00+00:00')""")
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()

    conn = db.connect(db_path)  # triggers the migration
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2

    run = db.get_latest_run(conn, 'bend--or')
    assert run.run_id == 7 and run.provider == 'gsv'
    assert run.unique_panos == 100 and run.unique_google_panos == 90
    assert db.get_api_usage(conn, date(2026, 4, 1)) == 12345
    row = conn.execute(
        "SELECT provider, day_of_cycle FROM schedule_state").fetchone()
    assert (row['provider'], row['day_of_cycle']) == ('gsv', 42)
    assert db.get_diff_for_run(conn, 7)['grid_aligned'] == 1

    # Idempotent: reopening must not migrate again or lose anything
    conn.close()
    conn2 = db.connect(db_path)
    assert db.get_latest_run(conn2, 'bend--or').run_id == 7
    conn2.close()

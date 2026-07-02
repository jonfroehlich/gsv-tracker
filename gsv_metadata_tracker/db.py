"""
SQLite catalog for GSV Tracker temporal data.

The database (default: data/gsv_tracker.db) is the operational source of
truth for city identity, frozen grid geometry, collection runs, run-to-run
diffs, the daily API-request budget ledger, and scheduler state. It is a
local catalog only — published artifacts (csv.gz / json.gz) are generated
from it and the raw files; the DB itself is never synced to the web server.

Key design point: grid geometry (center, dims, step) is FROZEN in the
cities table at registration. Future runs read geometry from the DB and
never re-geocode, so grids align exactly across quarters and diffs are
meaningful.

Uses stdlib sqlite3 with WAL mode; no ORM. All timestamps are UTC ISO 8601
strings; all dates are 'YYYY-MM-DD' strings.
"""

import hashlib
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import List, Optional

from .naming import sanitize_city_query_str

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cities (
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

CREATE TABLE IF NOT EXISTS city_aliases (
    alias_slug     TEXT PRIMARY KEY,
    city_id        TEXT NOT NULL REFERENCES cities(city_id)
);

CREATE TABLE IF NOT EXISTS runs (
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
CREATE INDEX IF NOT EXISTS idx_runs_city_date ON runs(city_id, run_date DESC);

CREATE TABLE IF NOT EXISTS run_diffs (
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

CREATE TABLE IF NOT EXISTS api_usage (
    usage_date  TEXT PRIMARY KEY,
    requests    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schedule_state (
    city_id              TEXT PRIMARY KEY REFERENCES cities(city_id),
    day_of_cycle         INTEGER NOT NULL,
    last_attempt_at      TEXT,
    last_success_at      TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error           TEXT
);
"""


@dataclass
class CityRow:
    """A row from the cities table."""
    city_id: str
    display_name: str
    city_name: str
    state_name: Optional[str]
    state_code: Optional[str]
    country_name: Optional[str]
    country_code: Optional[str]
    center_lat: float
    center_lon: float
    grid_width_m: int
    grid_height_m: int
    step_m: int
    created_at: str
    enabled: bool
    notes: Optional[str]


@dataclass
class RunRow:
    """A row from the runs table."""
    run_id: int
    city_id: str
    run_date: str
    csv_filename: str
    json_filename: Optional[str]
    is_baseline: bool
    started_at: Optional[str]
    finished_at: Optional[str]
    duration_seconds: Optional[float]
    total_points: Optional[int]
    status_ok: Optional[int]
    status_zero_results: Optional[int]
    status_other: Optional[int]
    unique_panos: Optional[int]
    unique_google_panos: Optional[int]
    coverage_rate_pct: Optional[float]
    oldest_capture_date: Optional[str]
    newest_capture_date: Optional[str]
    median_pano_age_years: Optional[float]
    api_requests: Optional[int]


def utc_now_iso() -> str:
    """Current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def get_default_db_path(data_dir: str) -> str:
    """The catalog lives alongside the data it describes."""
    return os.path.join(data_dir, "gsv_tracker.db")


def connect(db_path: str) -> sqlite3.Connection:
    """
    Open (creating if needed) the catalog database with WAL mode and
    foreign keys enabled, and ensure the schema exists.
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if needed and stamp the schema version."""
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if user_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {user_version} is newer than this code "
            f"supports ({SCHEMA_VERSION}). Update the code before proceeding.")
    conn.executescript(_SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def derive_city_id(city_name: str, state_name: Optional[str],
                   country_name: Optional[str]) -> str:
    """
    Canonical city id: the sanitized slug of the full (never abbreviated)
    location names, e.g. 'albany--new-york--united-states'. Derived once at
    registration; thereafter it is a stored key immune to geocoder drift.
    """
    components = [c for c in (city_name, state_name, country_name) if c]
    return sanitize_city_query_str(", ".join(components))


def register_city(conn: sqlite3.Connection, *,
                  city_name: str,
                  state_name: Optional[str],
                  state_code: Optional[str],
                  country_name: Optional[str],
                  country_code: Optional[str],
                  center_lat: float,
                  center_lon: float,
                  grid_width_m: float,
                  grid_height_m: float,
                  step_m: float,
                  notes: Optional[str] = None) -> str:
    """
    Register a city with its frozen grid geometry. Idempotent: if the city
    already exists, the existing row wins (geometry is never overwritten).

    Returns the canonical city_id.
    """
    city_id = derive_city_id(city_name, state_name, country_name)
    display_parts = [c for c in (city_name, state_name, country_name) if c]
    conn.execute(
        """INSERT OR IGNORE INTO cities
           (city_id, display_name, city_name, state_name, state_code,
            country_name, country_code, center_lat, center_lon,
            grid_width_m, grid_height_m, step_m, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (city_id, ", ".join(display_parts), city_name, state_name, state_code,
         country_name, country_code, center_lat, center_lon,
         int(grid_width_m), int(grid_height_m), int(step_m), utc_now_iso()))
    conn.commit()
    return city_id


def add_alias(conn: sqlite3.Connection, alias_slug: str, city_id: str) -> None:
    """Map a legacy filename slug (e.g. 'albany--ny') to a canonical city."""
    conn.execute(
        "INSERT OR IGNORE INTO city_aliases (alias_slug, city_id) VALUES (?, ?)",
        (alias_slug, city_id))
    conn.commit()


def resolve_city(conn: sqlite3.Connection, query: str) -> Optional[CityRow]:
    """
    Resolve a city query string or slug to its catalog row.

    Tries, in order: exact city_id match on the sanitized query, an alias
    match, then a display_name match (case-insensitive).
    """
    slug = sanitize_city_query_str(query)
    row = conn.execute(
        "SELECT * FROM cities WHERE city_id = ?", (slug,)).fetchone()
    if row is None:
        row = conn.execute(
            """SELECT c.* FROM cities c
               JOIN city_aliases a ON a.city_id = c.city_id
               WHERE a.alias_slug = ?""", (slug,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM cities WHERE lower(display_name) = lower(?)",
            (query.strip(),)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d['enabled'] = bool(d['enabled'])
    return CityRow(**d)


def register_run(conn: sqlite3.Connection, *,
                 city_id: str,
                 run_date: date,
                 csv_filename: str,
                 json_filename: Optional[str] = None,
                 is_baseline: bool = False,
                 started_at: Optional[str] = None,
                 finished_at: Optional[str] = None,
                 duration_seconds: Optional[float] = None,
                 total_points: Optional[int] = None,
                 status_ok: Optional[int] = None,
                 status_zero_results: Optional[int] = None,
                 status_other: Optional[int] = None,
                 unique_panos: Optional[int] = None,
                 unique_google_panos: Optional[int] = None,
                 coverage_rate_pct: Optional[float] = None,
                 oldest_capture_date: Optional[str] = None,
                 newest_capture_date: Optional[str] = None,
                 median_pano_age_years: Optional[float] = None,
                 api_requests: Optional[int] = None) -> int:
    """
    Register a completed collection run. Raises sqlite3.IntegrityError if a
    run already exists for (city_id, run_date) or the csv_filename is taken.

    Returns the new run_id.
    """
    cur = conn.execute(
        """INSERT INTO runs
           (city_id, run_date, csv_filename, json_filename, is_baseline,
            started_at, finished_at, duration_seconds, total_points,
            status_ok, status_zero_results, status_other,
            unique_panos, unique_google_panos, coverage_rate_pct,
            oldest_capture_date, newest_capture_date, median_pano_age_years,
            api_requests)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (city_id, run_date.isoformat(), csv_filename, json_filename,
         int(is_baseline), started_at, finished_at, duration_seconds,
         total_points, status_ok, status_zero_results, status_other,
         unique_panos, unique_google_panos, coverage_rate_pct,
         oldest_capture_date, newest_capture_date, median_pano_age_years,
         api_requests))
    conn.commit()
    return cur.lastrowid


def update_run_json_filename(conn: sqlite3.Connection, run_id: int,
                             json_filename: str) -> None:
    """Record the per-run summary JSON filename after it is generated."""
    conn.execute("UPDATE runs SET json_filename = ? WHERE run_id = ?",
                 (json_filename, run_id))
    conn.commit()


def _row_to_run(row: sqlite3.Row) -> RunRow:
    d = dict(row)
    d['is_baseline'] = bool(d['is_baseline'])
    return RunRow(**d)


def get_latest_run(conn: sqlite3.Connection, city_id: str) -> Optional[RunRow]:
    """Most recent run for a city by run_date, or None."""
    row = conn.execute(
        "SELECT * FROM runs WHERE city_id = ? ORDER BY run_date DESC LIMIT 1",
        (city_id,)).fetchone()
    return _row_to_run(row) if row else None


def get_previous_run(conn: sqlite3.Connection, city_id: str,
                     before_date: date) -> Optional[RunRow]:
    """Most recent run strictly before the given date, or None."""
    row = conn.execute(
        """SELECT * FROM runs WHERE city_id = ? AND run_date < ?
           ORDER BY run_date DESC LIMIT 1""",
        (city_id, before_date.isoformat())).fetchone()
    return _row_to_run(row) if row else None


def get_runs_for_city(conn: sqlite3.Connection, city_id: str) -> List[RunRow]:
    """All runs for a city, oldest first."""
    rows = conn.execute(
        "SELECT * FROM runs WHERE city_id = ? ORDER BY run_date ASC",
        (city_id,)).fetchall()
    return [_row_to_run(r) for r in rows]


def get_all_cities(conn: sqlite3.Connection,
                   enabled_only: bool = False) -> List[CityRow]:
    """All registered cities, ordered by city_id."""
    sql = "SELECT * FROM cities"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY city_id"
    out = []
    for row in conn.execute(sql).fetchall():
        d = dict(row)
        d['enabled'] = bool(d['enabled'])
        out.append(CityRow(**d))
    return out


def record_diff(conn: sqlite3.Connection, *,
                city_id: str,
                from_run_id: int,
                to_run_id: int,
                grid_aligned: bool,
                panos_added: int,
                panos_removed: int,
                panos_persisted: int,
                capture_date_changed: int,
                points_gained_coverage: Optional[int],
                points_lost_coverage: Optional[int],
                coverage_delta_pct: Optional[float],
                detail_filename: Optional[str]) -> int:
    """Store a run-to-run diff summary. Idempotent on (from_run, to_run)."""
    cur = conn.execute(
        """INSERT OR REPLACE INTO run_diffs
           (city_id, from_run_id, to_run_id, grid_aligned,
            panos_added, panos_removed, panos_persisted, capture_date_changed,
            points_gained_coverage, points_lost_coverage, coverage_delta_pct,
            detail_filename, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (city_id, from_run_id, to_run_id, int(grid_aligned),
         panos_added, panos_removed, panos_persisted, capture_date_changed,
         points_gained_coverage, points_lost_coverage, coverage_delta_pct,
         detail_filename, utc_now_iso()))
    conn.commit()
    return cur.lastrowid


def get_diff_for_run(conn: sqlite3.Connection,
                     to_run_id: int) -> Optional[sqlite3.Row]:
    """The diff whose 'to' side is the given run, or None."""
    return conn.execute(
        "SELECT * FROM run_diffs WHERE to_run_id = ?", (to_run_id,)).fetchone()


# ── API budget ledger ──────────────────────────────────────────────────────

def add_api_usage(conn: sqlite3.Connection, usage_date: date, n: int) -> None:
    """Add n requests to the given date's ledger row."""
    conn.execute(
        """INSERT INTO api_usage (usage_date, requests) VALUES (?, ?)
           ON CONFLICT(usage_date) DO UPDATE SET requests = requests + ?""",
        (usage_date.isoformat(), n, n))
    conn.commit()


def get_api_usage(conn: sqlite3.Connection, usage_date: date) -> int:
    """Requests recorded for the given date (0 if none)."""
    row = conn.execute(
        "SELECT requests FROM api_usage WHERE usage_date = ?",
        (usage_date.isoformat(),)).fetchone()
    return row[0] if row else 0


# ── Scheduler state ────────────────────────────────────────────────────────

def compute_day_of_cycle(city_id: str, cycle_days: int) -> int:
    """
    Stable stagger assignment: hash the city_id onto a day of the cycle.
    Deterministic across machines and runs.
    """
    digest = hashlib.sha256(city_id.encode('utf-8')).hexdigest()
    return int(digest, 16) % cycle_days


def assign_schedule(conn: sqlite3.Connection, cycle_days: int) -> int:
    """
    Ensure every enabled city has a schedule_state row with its
    day_of_cycle. Recomputes day_of_cycle for all cities (stable hash, so
    existing assignments only change if cycle_days changed).

    Returns the number of cities assigned.
    """
    cities = get_all_cities(conn, enabled_only=True)
    for city in cities:
        day = compute_day_of_cycle(city.city_id, cycle_days)
        conn.execute(
            """INSERT INTO schedule_state (city_id, day_of_cycle)
               VALUES (?, ?)
               ON CONFLICT(city_id) DO UPDATE SET day_of_cycle = ?""",
            (city.city_id, day, day))
    conn.commit()
    return len(cities)


def get_due_cities(conn: sqlite3.Connection, *, today: date, cycle_days: int,
                   grace_days: int, max_consecutive_failures: int) -> List[CityRow]:
    """
    Cities due for collection today, ordered stalest-first so backlog
    self-heals after outages.

    A city is due when it is enabled, hasn't exceeded the failure cap, and
    either has never succeeded or its last success is at least
    (cycle_days - grace_days) old.
    """
    threshold = cycle_days - grace_days
    rows = conn.execute(
        """SELECT c.*, s.last_success_at, s.consecutive_failures
           FROM cities c
           LEFT JOIN schedule_state s ON s.city_id = c.city_id
           WHERE c.enabled = 1
             AND COALESCE(s.consecutive_failures, 0) < ?
             AND (s.last_success_at IS NULL
                  OR julianday(?) - julianday(s.last_success_at) >= ?)
           ORDER BY s.last_success_at ASC NULLS FIRST, c.city_id ASC""",
        (max_consecutive_failures, today.isoformat(), threshold)).fetchall()
    out = []
    for row in rows:
        d = {k: row[k] for k in row.keys()
             if k not in ('last_success_at', 'consecutive_failures')}
        d['enabled'] = bool(d['enabled'])
        out.append(CityRow(**d))
    return out


def record_attempt(conn: sqlite3.Connection, city_id: str, *,
                   success: bool, error: Optional[str] = None) -> None:
    """Update schedule_state after a collection attempt."""
    now = utc_now_iso()
    if success:
        conn.execute(
            """INSERT INTO schedule_state
               (city_id, day_of_cycle, last_attempt_at, last_success_at,
                consecutive_failures, last_error)
               VALUES (?, 0, ?, ?, 0, NULL)
               ON CONFLICT(city_id) DO UPDATE SET
                 last_attempt_at = ?, last_success_at = ?,
                 consecutive_failures = 0, last_error = NULL""",
            (city_id, now, now, now, now))
    else:
        conn.execute(
            """INSERT INTO schedule_state
               (city_id, day_of_cycle, last_attempt_at,
                consecutive_failures, last_error)
               VALUES (?, 0, ?, 1, ?)
               ON CONFLICT(city_id) DO UPDATE SET
                 last_attempt_at = ?,
                 consecutive_failures = consecutive_failures + 1,
                 last_error = ?""",
            (city_id, now, error, now, error))
    conn.commit()

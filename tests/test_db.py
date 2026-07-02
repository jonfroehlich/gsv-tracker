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

"""Tests for scripts/purge_tainted_runs.py: identify runs whose snapshots
contain OVER_QUERY_LIMIT rows (the 2026-07-16 quota-throttling incident) and
purge their catalog rows + files so the same run date can be re-collected.
"""

import os
from datetime import date

import pytest

from scripts.purge_tainted_runs import count_over_query_limit, find_tainted_runs, purge_run
from streetscape_metadata_tracker import db
from tests.conftest import make_city_df, write_city_csv_gz


@pytest.fixture
def catalog(conn, data_dir):
    """One city with a clean 07-15 run and a throttle-tainted 07-16 run,
    linked by a diff with a published detail file."""
    city_id = db.register_city(
        conn,
        city_name="Bend",
        state_name="Oregon",
        state_code="OR",
        country_name="United States",
        country_code="us",
        center_lat=44.05,
        center_lon=-121.31,
        grid_width_m=1000,
        grid_height_m=1000,
        step_m=20,
    )

    clean_csv = f"{city_id}_width_1000_height_1000_step_20_2026-07-15.csv.gz"
    write_city_csv_gz(make_city_df([("p1", "2020-05-01")]), os.path.join(data_dir, clean_csv))
    clean_run = db.register_run(
        conn, city_id=city_id, run_date=date(2026, 7, 15), csv_filename=clean_csv, total_points=2
    )

    tainted_df = make_city_df([("p1", "2020-05-01")], n_empty=2)
    tainted_df.loc[tainted_df.index[-1], "status"] = "OVER_QUERY_LIMIT"
    tainted_csv = f"{city_id}_width_1000_height_1000_step_20_2026-07-16.csv.gz"
    tainted_json = tainted_csv.replace(".csv.gz", ".json.gz")
    write_city_csv_gz(tainted_df, os.path.join(data_dir, tainted_csv))
    with open(os.path.join(data_dir, tainted_json), "w") as f:
        f.write("{}")
    tainted_run = db.register_run(
        conn,
        city_id=city_id,
        run_date=date(2026, 7, 16),
        csv_filename=tainted_csv,
        json_filename=tainted_json,
        total_points=3,
    )

    detail = f"{city_id}_diff_2026-07-15_to_2026-07-16.csv.gz"
    with open(os.path.join(data_dir, detail), "w") as f:
        f.write("x")
    db.record_diff(
        conn,
        city_id=city_id,
        from_run_id=clean_run,
        to_run_id=tainted_run,
        grid_aligned=True,
        panos_added=0,
        panos_removed=0,
        panos_persisted=1,
        capture_date_changed=0,
        points_gained_coverage=0,
        points_lost_coverage=0,
        coverage_delta_pct=0.0,
        detail_filename=detail,
    )
    return conn, data_dir, city_id, clean_run, tainted_run


def test_count_over_query_limit(catalog):
    conn, data_dir, city_id, clean_run, tainted_run = catalog
    clean = conn.execute("SELECT csv_filename FROM runs WHERE run_id = ?", (clean_run,)).fetchone()
    bad = conn.execute("SELECT csv_filename FROM runs WHERE run_id = ?", (tainted_run,)).fetchone()
    assert count_over_query_limit(os.path.join(data_dir, clean["csv_filename"])) == 0
    assert count_over_query_limit(os.path.join(data_dir, bad["csv_filename"])) == 1


def test_find_tainted_runs_only_flags_the_throttled_date(catalog):
    conn, data_dir, *_ = catalog
    assert find_tainted_runs(conn, data_dir, "2026-07-15", None) == []
    tainted = find_tainted_runs(conn, data_dir, "2026-07-16", None)
    assert len(tainted) == 1
    assert tainted[0]["over_query_limit"] == 1


def test_dry_run_deletes_nothing(catalog):
    conn, data_dir, city_id, clean_run, tainted_run = catalog
    [item] = find_tainted_runs(conn, data_dir, "2026-07-16", "gsv")
    purge_run(conn, data_dir, item["run"], execute=False)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM run_diffs").fetchone()[0] == 1
    assert os.path.exists(os.path.join(data_dir, item["run"]["csv_filename"]))


def test_purge_removes_rows_and_files_but_keeps_clean_run(catalog):
    conn, data_dir, city_id, clean_run, tainted_run = catalog
    [item] = find_tainted_runs(conn, data_dir, "2026-07-16", "gsv")
    run = item["run"]
    purge_run(conn, data_dir, run, execute=True)

    # Tainted run gone: rows and every file (snapshot, json, diff detail)
    assert conn.execute("SELECT * FROM runs WHERE run_id = ?", (tainted_run,)).fetchone() is None
    assert conn.execute("SELECT COUNT(*) FROM run_diffs").fetchone()[0] == 0
    assert not os.path.exists(os.path.join(data_dir, run["csv_filename"]))
    assert not os.path.exists(os.path.join(data_dir, run["json_filename"]))
    assert not os.path.exists(
        os.path.join(data_dir, f"{city_id}_diff_2026-07-15_to_2026-07-16.csv.gz")
    )

    # Clean run and frozen city geometry untouched
    clean = conn.execute("SELECT * FROM runs WHERE run_id = ?", (clean_run,)).fetchone()
    assert clean is not None
    assert os.path.exists(os.path.join(data_dir, clean["csv_filename"]))
    assert db.resolve_city(conn, city_id) is not None

    # The same (city, provider, run_date) can now be re-registered
    db.register_run(
        conn,
        city_id=city_id,
        run_date=date(2026, 7, 16),
        csv_filename=run["csv_filename"],
        total_points=3,
    )

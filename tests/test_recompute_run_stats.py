"""End-to-end test for scripts/recompute_run_stats.py (the v3 stats backfill).

Runs the real script as a subprocess against a fixture catalog: a run whose
stored stats predate the v3 "NO_DATE counts as present imagery" definition
gets rewritten to match analysis.calculate_run_stats, and a second dry run
confirms idempotence. This is the harness the next stats-definition bump
(v4) will rely on.
"""

import os
import subprocess
import sys
from datetime import date

import pandas as pd

from streetscape_metadata_tracker import db
from streetscape_metadata_tracker.analysis import calculate_run_stats
from streetscape_metadata_tracker.fileutils import load_city_csv_file
from tests.conftest import COLUMNS, make_city_df, write_city_csv_gz

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_PROJECT_ROOT, "scripts", "recompute_run_stats.py")


def _run_script(data_dir, *extra):
    return subprocess.run(
        [sys.executable, _SCRIPT, "--data-dir", data_dir, "--no-publish-json", *extra],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_recompute_rewrites_stale_stats_then_is_idempotent(conn, data_dir):
    run_date = date(2026, 4, 15)
    cid = db.register_city(
        conn,
        city_name="Bend",
        state_name="Oregon",
        state_code="OR",
        country_name="United States",
        country_code="US",
        center_lat=44.0,
        center_lon=-121.0,
        grid_width_m=1000,
        grid_height_m=1000,
        step_m=20,
    )

    # Two dated panos + one ZERO_RESULTS point + one NO_DATE pano (the row
    # class whose accounting changed in v3)
    df = make_city_df([("p1", "2020-06-15"), ("p2", "2024-01-10")], run_date=run_date, n_empty=1)
    ts = df.iloc[0]["query_timestamp"]
    no_date_row = pd.DataFrame(
        [[44.9, -121.0, ts, 44.9001, -121.0001, "p_nodate", None, "© Google", "NO_DATE"]],
        columns=COLUMNS,
    )
    df = pd.concat([df, no_date_row], ignore_index=True)

    csv_name = "bend--oregon--united-states_width_1000_height_1000_step_20_2026-04-15.csv.gz"
    csv_path = os.path.join(data_dir, csv_name)
    write_city_csv_gz(df, csv_path)

    # Stored stats simulate the pre-v3 catalog: NO_DATE folded into
    # status_other, its pano missing from every total
    db.register_run(
        conn,
        city_id=cid,
        run_date=run_date,
        csv_filename=csv_name,
        total_points=4,
        status_ok=2,
        status_no_date=0,
        status_zero_results=1,
        status_other=1,
        unique_panos=2,
        unique_google_panos=2,
        coverage_rate_pct=50.0,
    )

    result = _run_script(data_dir, "--execute")
    assert result.returncode == 0, result.stderr

    expected = calculate_run_stats(load_city_csv_file(csv_path), run_date, provider="gsv")
    row = conn.execute(
        """SELECT total_points, status_ok, status_no_date, status_other,
                  unique_panos, unique_google_panos, coverage_rate_pct
           FROM runs WHERE city_id = ?""",
        (cid,),
    ).fetchone()
    assert row["status_no_date"] == expected["status_no_date"] == 1
    assert row["status_other"] == expected["status_other"] == 0
    assert row["unique_panos"] == expected["unique_panos"] == 3  # NO_DATE pano now counted
    assert row["coverage_rate_pct"] == expected["coverage_rate_pct"]
    assert row["total_points"] == expected["total_points"]

    # Second pass: nothing left to change
    rerun = _run_script(data_dir)
    assert rerun.returncode == 0, rerun.stderr
    assert "0 would change" in rerun.stdout


def test_recompute_skips_runs_with_missing_csv(conn, data_dir):
    cid = db.register_city(
        conn,
        city_name="Ghost",
        state_name="Oregon",
        state_code="OR",
        country_name="United States",
        country_code="US",
        center_lat=44.0,
        center_lon=-121.0,
        grid_width_m=1000,
        grid_height_m=1000,
        step_m=20,
    )
    db.register_run(
        conn,
        city_id=cid,
        run_date=date(2026, 4, 15),
        csv_filename="ghost--never-written.csv.gz",
        unique_panos=7,
    )

    result = _run_script(data_dir, "--execute")
    assert result.returncode == 0, result.stderr
    assert "1 skipped (missing CSV)" in result.stdout
    # The stored values survive untouched
    row = conn.execute("SELECT unique_panos FROM runs WHERE city_id = ?", (cid,)).fetchone()
    assert row["unique_panos"] == 7

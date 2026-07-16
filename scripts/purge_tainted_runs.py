#!/usr/bin/env python3
"""
Purge runs whose snapshots contain OVER_QUERY_LIMIT rows so they can be
re-collected cleanly.

Background (2026-07-16): before client-side rate limiting, a fast host could
exceed the GSV metadata per-minute quota mid-run; the throttled responses
were written into the immutable snapshot as final rows, where they read as
"no imagery" and corrupt coverage rates and every future diff. Runs are
immutable and UNIQUE(city_id, provider, run_date), so re-collecting the same
run date first requires deleting the catalog rows and the snapshot files.

For each run on --run-date (all providers unless --provider is given), the
CSV is scanned for OVER_QUERY_LIMIT rows. Tainted runs are purged:

1. run_diffs rows referencing the run, plus their published detail files
2. the runs row itself
3. the snapshot .csv.gz, its per-run .json.gz, and any _failed_points.csv

The frozen city geometry, aliases, api_usage ledger, and schedule_state are
untouched. Re-collect afterwards with the SAME run date so every published
filename is overwritten in place, then regenerate the aggregate:

    python streetscape_tracker.py "<City>" --provider gsv --force \
        --run-date YYYY-MM-DD --download-dir DIR --db-path PATH
    python -m streetscape_metadata_tracker.scheduler regenerate-aggregate --publish

Usage:
    python scripts/purge_tainted_runs.py --run-date 2026-07-16            # dry run (default)
    python scripts/purge_tainted_runs.py --run-date 2026-07-16 --execute  # apply
    python scripts/purge_tainted_runs.py --run-date 2026-07-16 --provider gsv \
        --data-dir DIR --db-path PATH
"""

import argparse
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streetscape_metadata_tracker import db  # noqa: E402
from streetscape_metadata_tracker.paths import get_default_data_dir  # noqa: E402

logger = logging.getLogger("purge_tainted_runs")


def count_over_query_limit(csv_gz_path: str) -> int:
    """Number of OVER_QUERY_LIMIT rows in a run snapshot (0 if file missing)."""
    if not os.path.exists(csv_gz_path):
        logger.warning(f"Snapshot file missing, treating as clean: {csv_gz_path}")
        return 0
    status = pd.read_csv(csv_gz_path, usecols=["status"], dtype=str)["status"]
    return int((status == "OVER_QUERY_LIMIT").sum())


def find_tainted_runs(conn, data_dir: str, run_date: str, provider: str | None) -> list[dict]:
    """All runs on run_date whose CSV contains OVER_QUERY_LIMIT rows."""
    sql = "SELECT * FROM runs WHERE run_date = ?"
    params: list = [run_date]
    if provider:
        sql += " AND provider = ?"
        params.append(provider)
    tainted = []
    for run in conn.execute(sql + " ORDER BY run_id", params).fetchall():
        n = count_over_query_limit(os.path.join(data_dir, run["csv_filename"]))
        if n > 0:
            tainted.append({"run": run, "over_query_limit": n})
    return tainted


def purge_run(conn, data_dir: str, run, execute: bool) -> None:
    """Delete one run's catalog rows and files (or just narrate, when not execute)."""
    run_id = run["run_id"]
    verb = "DELETE" if execute else "would delete"

    files = [run["csv_filename"], run["json_filename"]]
    diffs = conn.execute(
        "SELECT diff_id, detail_filename FROM run_diffs WHERE from_run_id = ? OR to_run_id = ?",
        (run_id, run_id),
    ).fetchall()
    files.extend(d["detail_filename"] for d in diffs)
    failed_sidecar = run["csv_filename"].replace(".csv.gz", "_failed_points.csv")
    files.append(failed_sidecar)

    for d in diffs:
        logger.info(f"  {verb} run_diffs row diff_id={d['diff_id']}")
    logger.info(f"  {verb} runs row run_id={run_id}")
    if execute:
        conn.execute(
            "DELETE FROM run_diffs WHERE from_run_id = ? OR to_run_id = ?", (run_id, run_id)
        )
        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()

    for name in files:
        if not name:
            continue
        path = os.path.join(data_dir, name)
        if os.path.exists(path):
            logger.info(f"  {verb} file {path}")
            if execute:
                os.remove(path)
        elif name != failed_sidecar:  # the sidecar is usually absent; others should exist
            logger.warning(f"  file already missing: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--run-date", required=True, help="Run date to scan (YYYY-MM-DD)")
    parser.add_argument("--provider", default=None, help="Restrict to one provider (default: all)")
    parser.add_argument("--data-dir", default=None, help="Data directory (default: ./data)")
    parser.add_argument("--db-path", default=None, help="Catalog DB path (default: in data dir)")
    parser.add_argument(
        "--execute", action="store_true", help="Apply the deletions (default: dry run)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    data_dir = args.data_dir or get_default_data_dir()
    db_path = args.db_path or db.get_default_db_path(data_dir)
    conn = db.connect(db_path)
    try:
        tainted = find_tainted_runs(conn, data_dir, args.run_date, args.provider)
        if not tainted:
            logger.info(f"No tainted runs on {args.run_date}. Nothing to do.")
            return 0

        mode = "EXECUTING" if args.execute else "DRY RUN (pass --execute to apply)"
        logger.info(f"{mode}: {len(tainted)} tainted run(s) on {args.run_date}\n")
        for item in tainted:
            run = item["run"]
            pct = 100.0 * item["over_query_limit"] / run["total_points"]
            logger.info(
                f"{run['city_id']} [{run['provider']}]: "
                f"{item['over_query_limit']:,} OVER_QUERY_LIMIT rows "
                f"of {run['total_points']:,} points ({pct:.1f}%)"
            )
            purge_run(conn, data_dir, run, args.execute)
            logger.info("")

        if args.execute:
            logger.info(
                "Purged. Re-collect each city with the SAME --run-date and --force, "
                "then regenerate-aggregate --publish."
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
One-shot recompute of every run's stored stats from its CSV, under the
current analysis definitions (schema v3).

v3 changed what "present imagery" means: a pano the provider returned but
whose capture date we couldn't read (status NO_DATE) now counts toward both
coverage and pano totals, instead of sitting in the status_other error
bucket (see analysis.PRESENT_STATUSES). Because the pre-v3 catalog folded
NO_DATE into status_other, the corrected numbers cannot be recovered with
pure SQL — every run's CSV is reloaded and re-summarized with
analysis.calculate_run_stats, the same function the live pipeline uses.

Columns refreshed per run: total_points, status_ok, status_no_date,
status_zero_results, status_other, unique_panos, unique_google_panos,
coverage_rate_pct, oldest/newest_capture_date, median_pano_age_years.

Per-run JSON summaries are NOT regenerated (they refresh on each city's next
run); the aggregate cities.json.gz IS regenerated since the overview site
reads coverage from it.

Idempotent: a run whose stored stats already match is left untouched. Runs
whose CSV is missing (skipped, reported) keep their existing values.

Usage:
    python scripts/recompute_run_stats.py            # dry run
    python scripts/recompute_run_stats.py --execute  # apply
"""

import argparse
import logging
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gsv_metadata_tracker import db  # noqa: E402
from gsv_metadata_tracker.analysis import calculate_run_stats  # noqa: E402
from gsv_metadata_tracker.fileutils import load_city_csv_file  # noqa: E402
from gsv_metadata_tracker.json_summarizer import generate_aggregate_v2  # noqa: E402
from gsv_metadata_tracker.paths import get_default_data_dir  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Stat columns owned by calculate_run_stats that this script refreshes.
STAT_COLUMNS = (
    "total_points",
    "status_ok",
    "status_no_date",
    "status_zero_results",
    "status_other",
    "unique_panos",
    "unique_google_panos",
    "coverage_rate_pct",
    "oldest_capture_date",
    "newest_capture_date",
    "median_pano_age_years",
)


def _equalish(a, b) -> bool:
    """Compare stored vs recomputed values, tolerant of float noise/None."""
    if a is None or b is None:
        return a is b or a == b
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
    return a == b


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute stored per-run stats from CSVs (schema v3: "
        "NO_DATE counts as present imagery)"
    )
    parser.add_argument("--data-dir", default=get_default_data_dir())
    parser.add_argument(
        "--execute", action="store_true", help="Apply changes (default is a dry-run report)"
    )
    parser.add_argument(
        "--no-publish-json",
        action="store_true",
        help="Skip regenerating the aggregate cities.json.gz",
    )
    args = parser.parse_args()

    conn = db.connect(db.get_default_db_path(args.data_dir))

    rows = conn.execute(
        """SELECT run_id, city_id, provider, run_date, csv_filename,
                  total_points, status_ok, status_no_date, status_zero_results,
                  status_other, unique_panos, unique_google_panos,
                  coverage_rate_pct, oldest_capture_date, newest_capture_date,
                  median_pano_age_years
           FROM runs ORDER BY city_id, provider, run_date"""
    ).fetchall()

    updates = []  # (run_id, {col: value})
    missing = 0
    for r in rows:
        csv_path = os.path.join(args.data_dir, r["csv_filename"])
        if not os.path.exists(csv_path):
            logger.warning(f"CSV missing, skipping: {r['csv_filename']}")
            missing += 1
            continue
        df = load_city_csv_file(csv_path)
        stats = calculate_run_stats(df, date.fromisoformat(r["run_date"]), provider=r["provider"])
        changed = {c: stats[c] for c in STAT_COLUMNS if not _equalish(r[c], stats[c])}
        if changed:
            updates.append((r["run_id"], changed))
            nd = stats["status_no_date"]
            cov_old = r["coverage_rate_pct"]
            cov_new = stats["coverage_rate_pct"]
            print(
                f"  {r['city_id']} [{r['provider']}] {r['run_date']}: "
                f"coverage {('NULL' if cov_old is None else f'{cov_old:.1f}%')}"
                f" -> {cov_new:.1f}%, unique_panos "
                f"{r['unique_panos']} -> {stats['unique_panos']}, "
                f"status_no_date -> {nd}"
            )

    print(
        f"\n{len(rows)} runs scanned, {missing} skipped (missing CSV), {len(updates)} would change"
    )

    if not args.execute:
        print("\nDry run complete. Re-run with --execute to apply.")
        return 0

    with conn:
        for run_id, changed in updates:
            assignments = ", ".join(f"{c} = ?" for c in changed)
            conn.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ?", (*changed.values(), run_id)
            )

    print(f"\nUpdated {len(updates)} runs.")
    if not args.no_publish_json:
        generate_aggregate_v2(conn, args.data_dir)
        print(f"Regenerated aggregate: {os.path.join(args.data_dir, 'cities.json.gz')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

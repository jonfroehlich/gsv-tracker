"""
One-shot recompute of runs.coverage_rate_pct to the points-with-pano
definition (issue #90).

The v2 migration briefly cataloged coverage as unique_panos / total_points
(a density proxy that collapses as the sampling step shrinks). The correct,
originally published definition is grid points with >= 1 pano / total grid
points. analysis.calculate_coverage_stats now computes the latter for new
runs; this script fixes the values already stored in the catalog.

- GSV runs: pure SQL — one row per grid point, so the rate is exactly
  100 * status_ok / total_points. No CSV re-reads.
- Non-GSV runs (Mapillary): rows are one-per-pano, so the stored
  status_ok/total_points are row counts, not point counts. Each run's
  CSV is reloaded and the rate recomputed via calculate_coverage_stats.

Per-run JSON summaries are NOT regenerated (they refresh on each city's
next run); the aggregate cities.json.gz IS regenerated since the overview
site reads coverage from it.

Idempotent: recomputing already-correct rows is a no-op.

SUPERSEDED by scripts/recompute_run_stats.py as of schema v3: the GSV
pure-SQL path here (100 * status_ok / total_points) predates NO_DATE counting
toward coverage, so running it against a v3 catalog would wrongly drop
dateless panos from GSV coverage. This script now refuses to run on v3+
databases.

Usage:
    python scripts/recompute_coverage_rates.py            # dry run
    python scripts/recompute_coverage_rates.py --execute  # apply
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gsv_metadata_tracker import db  # noqa: E402
from gsv_metadata_tracker.analysis import calculate_coverage_stats  # noqa: E402
from gsv_metadata_tracker.fileutils import load_city_csv_file  # noqa: E402
from gsv_metadata_tracker.json_summarizer import generate_aggregate_v2  # noqa: E402
from gsv_metadata_tracker.paths import get_default_data_dir  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Recompute runs.coverage_rate_pct to the '
                    'points-with-pano definition (issue #90)')
    parser.add_argument('--data-dir', default=get_default_data_dir())
    parser.add_argument('--execute', action='store_true',
                        help='Apply changes (default is a dry-run report)')
    parser.add_argument('--no-publish-json', action='store_true',
                        help='Skip regenerating the aggregate cities.json.gz')
    args = parser.parse_args()

    conn = db.connect(db.get_default_db_path(args.data_dir))

    # v3 redefined coverage to include NO_DATE; the GSV pure-SQL path below is
    # no longer correct. Refuse rather than silently regress GSV coverage.
    schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if schema_version >= 3:
        print("This script is superseded on schema v3+. "
              "Use scripts/recompute_run_stats.py instead.")
        return 1

    # ── GSV: one row per grid point, recompute from stored counters ──────
    gsv_rows = conn.execute(
        """SELECT run_id, city_id, run_date, coverage_rate_pct,
                  100.0 * status_ok / total_points AS new_rate
           FROM runs
           WHERE provider = 'gsv' AND total_points > 0""").fetchall()
    gsv_changed = [r for r in gsv_rows
                   if r['coverage_rate_pct'] is None
                   or abs(r['coverage_rate_pct'] - r['new_rate']) > 1e-9]
    print(f"GSV runs: {len(gsv_rows)} recomputable, "
          f"{len(gsv_changed)} would change")
    for r in gsv_changed[:10]:
        old = r['coverage_rate_pct']
        print(f"  {r['city_id']} {r['run_date']}: "
              f"{old:.1f}% -> {r['new_rate']:.1f}%" if old is not None
              else f"  {r['city_id']} {r['run_date']}: "
                   f"NULL -> {r['new_rate']:.1f}%")
    if len(gsv_changed) > 10:
        print(f"  ... and {len(gsv_changed) - 10} more")

    # ── Non-GSV: rows are per-pano, so recompute from the CSV ────────────
    other_rows = conn.execute(
        """SELECT run_id, city_id, provider, run_date, csv_filename,
                  coverage_rate_pct
           FROM runs WHERE provider != 'gsv'""").fetchall()
    other_updates = []
    for r in other_rows:
        csv_path = os.path.join(args.data_dir, r['csv_filename'])
        if not os.path.exists(csv_path):
            logger.warning(f"CSV missing, skipping: {csv_path}")
            continue
        df = load_city_csv_file(csv_path)
        new_rate = calculate_coverage_stats(df).coverage_rate
        old = r['coverage_rate_pct']
        if old is None or abs(old - new_rate) > 1e-9:
            other_updates.append((r['run_id'], new_rate))
            print(f"  {r['city_id']} [{r['provider']}] {r['run_date']}: "
                  f"{old if old is None else f'{old:.1f}%'} "
                  f"-> {new_rate:.1f}%")
    print(f"{len(other_rows)} non-GSV runs, {len(other_updates)} would change")

    if not args.execute:
        print("\nDry run complete. Re-run with --execute to apply.")
        return 0

    with conn:
        conn.execute(
            """UPDATE runs
               SET coverage_rate_pct = 100.0 * status_ok / total_points
               WHERE provider = 'gsv' AND total_points > 0""")
        conn.executemany(
            "UPDATE runs SET coverage_rate_pct = ? WHERE run_id = ?",
            [(rate, run_id) for run_id, rate in other_updates])

    print(f"\nUpdated {len(gsv_changed)} GSV + {len(other_updates)} "
          f"non-GSV runs.")
    if not args.no_publish_json:
        generate_aggregate_v2(conn, args.data_dir)
        print(f"Regenerated aggregate: "
              f"{os.path.join(args.data_dir, 'cities.json.gz')}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

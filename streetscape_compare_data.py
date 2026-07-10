#!/usr/bin/env python3
"""
Streetscape run comparison tool.

Compares two run metadata files for the same city and reports what changed:
panoramas added/removed, capture-date changes, and (when both files sampled
the same grid) coverage transitions. Provider-agnostic — works on any
provider's run files. This is a thin CLI over
streetscape_metadata_tracker.diff.compute_run_diff — the same engine the tracker
uses to diff consecutive scheduled runs.

Usage:
    python streetscape_compare_data.py old.csv.gz new.csv.gz [--verbose] [--out diff.csv.gz]

Exit codes:
    0: No pano-level changes between the files
    1: Files differ (see report)
    2: Error occurred during comparison
"""

import argparse
import logging
import sys

from streetscape_metadata_tracker.diff import compute_run_diff, write_diff_detail
from streetscape_metadata_tracker.fileutils import load_city_csv_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two run metadata files")
    parser.add_argument("file_old", help="Path to the earlier run metadata file (.csv.gz)")
    parser.add_argument("file_new", help="Path to the later run metadata file (.csv.gz)")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-file status counts and change detail rows",
    )
    parser.add_argument(
        "--out", metavar="DIFF.csv.gz", help="Write the detailed change rows to a gzipped CSV"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    try:
        logging.info(f"Loading {args.file_old}...")
        df_old = load_city_csv_file(args.file_old)
        logging.info(f"Loading {args.file_new}...")
        df_new = load_city_csv_file(args.file_new)

        diff = compute_run_diff(df_old, df_new)

        print(f"\nComparison: {args.file_old} -> {args.file_new}")
        print("=" * 60)
        print(f"Panos added:            {diff.panos_added:,}")
        print(f"Panos removed:          {diff.panos_removed:,}")
        print(f"Panos persisted:        {diff.panos_persisted:,}")
        print(f"Capture date changed:   {diff.capture_date_changed:,}")
        if diff.grid_aligned:
            print(f"Points gained coverage: {diff.points_gained_coverage:,}")
            print(f"Points lost coverage:   {diff.points_lost_coverage:,}")
            print(f"Coverage delta:         {diff.coverage_delta_pct:+.2f} pct points")
        else:
            print("Query grids differ; coverage transitions not computed.")

        if args.verbose:
            print(f"\nFile 1 ({args.file_old}): {len(df_old):,} rows")
            print(df_old["status"].value_counts().to_string())
            print(f"\nFile 2 ({args.file_new}): {len(df_new):,} rows")
            print(df_new["status"].value_counts().to_string())
            if diff.has_changes:
                print("\nChange detail:")
                print(diff.detail.to_string(index=False, max_rows=50))

        if args.out:
            write_diff_detail(diff, args.out)
            print(f"\nWrote detail rows to {args.out}")

        return 1 if diff.has_changes else 0

    except Exception as e:
        logging.error(f"Error comparing files: {str(e)}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

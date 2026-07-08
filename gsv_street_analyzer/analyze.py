"""
CLI: compute OSM street coverage for an existing run and write a GeoJSON artifact.

    python -m gsv_street_analyzer.analyze "Seattle, WA" \
        [--provider gsv|mapillary] [--run-date YYYY-MM-DD] \
        [--match-dist 25] [--refresh] [--data-dir DIR]

Reads the catalog read-only to resolve the city and locate its run CSV, overlays
the (frozen) OSM drive network, tags each street segment as covered/uncovered,
and writes ``{run_stem}_streets.json.gz`` next to the run for the web frontend.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from typing import Optional

from gsv_metadata_tracker import db
from gsv_metadata_tracker.db import RunRow
from gsv_metadata_tracker.fileutils import load_city_csv_file
from gsv_metadata_tracker.paths import get_default_data_dir

from .download_street_network import fetch_street_edges
from .street_coverage import (
    DEFAULT_MATCH_DIST_M,
    build_streets_geojson,
    compute_street_coverage,
    select_pano_points,
)

logger = logging.getLogger(__name__)

_CSV_SUFFIX = ".csv.gz"


def _select_run(conn, city_id: str, provider: str, run_date: Optional[str]) -> Optional[RunRow]:
    """Latest run for the (city, provider), or the one on an explicit run_date."""
    if run_date is None:
        return db.get_latest_run(conn, city_id, provider)
    for run in db.get_runs_for_city(conn, city_id, provider):
        if run.run_date == run_date:
            return run
    return None


def run_analysis(args: argparse.Namespace) -> int:
    data_dir = args.data_dir
    db_path = db.get_default_db_path(data_dir)
    if not os.path.exists(db_path):
        logger.error("Catalog DB not found at %s", db_path)
        return 1

    conn = db.connect(db_path)
    try:
        city = db.resolve_city(conn, args.city)
        if city is None:
            logger.error("City not found in catalog: %s", args.city)
            return 1

        run = _select_run(conn, city.city_id, args.provider, args.run_date)
        if run is None:
            logger.error(
                "No %s run found for %s%s",
                args.provider,
                city.city_id,
                f" on {args.run_date}" if args.run_date else "",
            )
            return 1

        csv_path = os.path.join(data_dir, run.csv_filename)
        if not os.path.exists(csv_path):
            logger.error("Run CSV missing on disk: %s", csv_path)
            return 1

        logger.info("Analyzing %s (%s, run %s)", city.city_id, args.provider, run.run_date)
        df = load_city_csv_file(csv_path)
        panos = select_pano_points(df, args.provider)
        logger.info("Selected %d located panos", len(panos))

        edges = fetch_street_edges(city, data_dir, refresh=args.refresh)
        logger.info("Fetched %d street segments", len(edges))

        covered = compute_street_coverage(
            edges, panos, run.run_date, match_dist_m=args.match_dist
        )
        geojson = build_streets_geojson(
            covered,
            city_id=city.city_id,
            provider=args.provider,
            run_date=run.run_date,
            match_dist_m=args.match_dist,
            source_csv=run.csv_filename,
        )
    finally:
        conn.close()

    stem = run.csv_filename[: -len(_CSV_SUFFIX)] if run.csv_filename.endswith(
        _CSV_SUFFIX
    ) else os.path.splitext(run.csv_filename)[0]
    out_path = os.path.join(data_dir, f"{stem}_streets.json.gz")
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        json.dump(geojson, fh)

    totals = geojson["properties"]["metadata"]["totals"]
    logger.info("Wrote %s", out_path)
    print(
        f"{city.city_id} [{args.provider} {run.run_date}]: "
        f"{totals['covered']}/{totals['segments']} segments covered "
        f"({totals['coverage_pct_by_count']}% by count, "
        f"{totals['coverage_pct_by_length']}% by length); "
        f"{totals['uncovered_pct_by_length']}% of street-km have no coverage"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute OSM street coverage for an existing run."
    )
    parser.add_argument("city", help="City query or catalog slug (e.g. 'Seattle, WA')")
    parser.add_argument(
        "--provider", default="gsv", choices=["gsv", "mapillary"],
        help="Pano provider to score coverage against (default: gsv)",
    )
    parser.add_argument(
        "--run-date", default=None,
        help="Specific run date YYYY-MM-DD (default: latest run)",
    )
    parser.add_argument(
        "--match-dist", type=float, default=DEFAULT_MATCH_DIST_M,
        help=f"Coverage threshold in metres (default: {DEFAULT_MATCH_DIST_M})",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-download the OSM network instead of using the frozen cache",
    )
    parser.add_argument("--data-dir", default=get_default_data_dir(), help="Data directory")
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return run_analysis(args)


if __name__ == "__main__":
    sys.exit(main())

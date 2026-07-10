#!/usr/bin/env python3
"""
Apply reviewed boundary decisions back to the catalog (issue #91, part 3).

Closes the human-in-the-loop: ``scripts/build_boundary_review.py`` renders each
flagged city and the reviewer exports ``boundary_decisions.csv`` (one row per
city with a ``decision`` and the ``chosen_*`` geometry). This script reads that
CSV and writes the chosen geometry into the catalog via
``db.update_city_geometry`` — the same deliberate escape hatch the automatic
re-registration uses.

Policy (per row, driven by the exported ``decision`` + ``chosen_*`` geometry):
  * A row whose chosen geometry differs from the city's CURRENT catalog
    geometry -> APPLY (recenter/resize to the chosen rectangle).
  * A row whose chosen geometry equals the current geometry (e.g. "keep
    current" / "ok", or an "accept" that resolved to keep-current) -> NOCHANGE.
  * A row with a blank/undecided ``decision`` or no ``chosen_*`` geometry
    (skip / defer / rework) -> SKIP, geometry untouched.

Read live from the DB, so it is idempotent: re-running after --execute applies
nothing. Dry run by default. Makes ZERO provider API calls.

Usage:
    python scripts/apply_decisions.py                       # dry run (default)
    python scripts/apply_decisions.py --execute             # apply changes
    python scripts/apply_decisions.py --decisions PATH --db-path PATH
"""

import argparse
import csv
import logging
import math
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streetscape_metadata_tracker import db  # noqa: E402
from streetscape_metadata_tracker.paths import get_default_data_dir  # noqa: E402

logger = logging.getLogger("apply_decisions")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DECISIONS = os.path.join(_PROJECT_ROOT, "audit", "boundary_decisions.csv")

# Tolerances for "chosen == current" (center in degrees, size in meters).
_CENTER_EPS_DEG = 1e-7
_SIZE_EPS_M = 1.0

# Note stamped onto applied rows for the audit trail.
APPLY_NOTE = "regeom #91: applied reviewed boundary decision"


@dataclass
class Current:
    """A city's current frozen geometry, read live from the catalog."""

    center_lat: float
    center_lon: float
    width_m: int
    height_m: int


@dataclass
class Apply:
    """The action to take for one decision row."""

    city_id: str
    display_name: str
    decision: str
    action: str  # APPLY | NOCHANGE | SKIP
    reason: str
    old_center_lat: float | None = None
    old_center_lon: float | None = None
    old_width_m: int | None = None
    old_height_m: int | None = None
    new_center_lat: float | None = None
    new_center_lon: float | None = None
    new_width_m: int | None = None
    new_height_m: int | None = None


def _num(row: dict, key: str) -> float | None:
    """Parse a possibly-blank/NaN CSV cell to float, or None."""
    val = row.get(key, "")
    if val is None or val == "":
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _chosen(row: dict):
    """Chosen geometry tuple (lat, lon, w, h) or None if any field is blank."""
    lat, lon = _num(row, "chosen_center_lat"), _num(row, "chosen_center_lon")
    w, h = _num(row, "chosen_width_m"), _num(row, "chosen_height_m")
    if None in (lat, lon, w, h):
        return None
    return (lat, lon, int(w), int(h))


def plan_row(row: dict, current: Current | None) -> Apply:
    """
    Pure policy: map one decision-CSV row + current geometry to an Apply action.

    Current geometry is read from the catalog (passed in), never the CSV, so the
    result is idempotent and network-free.
    """
    city_id = row.get("city_id", "")
    name = row.get("display_name", city_id)
    decision = (row.get("decision") or "").strip()

    def a(action, reason, **kw):
        return Apply(
            city_id=city_id,
            display_name=name,
            decision=decision,
            action=action,
            reason=reason,
            **kw,
        )

    if current is None:
        return a("SKIP", "not found in catalog")

    old = dict(
        old_center_lat=current.center_lat,
        old_center_lon=current.center_lon,
        old_width_m=current.width_m,
        old_height_m=current.height_m,
    )

    chosen = _chosen(row)
    if not decision:
        return a("SKIP", "no decision recorded", **old)
    if chosen is None:
        # skip / defer / rework, or an accept that (correctly) exports no geometry.
        return a("SKIP", f"decision '{decision}' carries no geometry", **old)

    lat, lon, w, h = chosen
    unchanged = (
        abs(lat - current.center_lat) < _CENTER_EPS_DEG
        and abs(lon - current.center_lon) < _CENTER_EPS_DEG
        and abs(w - current.width_m) < _SIZE_EPS_M
        and abs(h - current.height_m) < _SIZE_EPS_M
    )
    new = dict(new_center_lat=lat, new_center_lon=lon, new_width_m=w, new_height_m=h)
    if unchanged:
        return a("NOCHANGE", f"decision '{decision}': chosen == current", **old, **new)
    return a("APPLY", f"decision '{decision}': recenter/resize to chosen", **old, **new)


def load_current_geometry(conn) -> dict:
    """Map city_id -> Current for every city in the catalog."""
    rows = conn.execute(
        "SELECT city_id, center_lat, center_lon, grid_width_m, grid_height_m FROM cities"
    ).fetchall()
    return {
        r["city_id"]: Current(
            r["center_lat"], r["center_lon"], r["grid_width_m"], r["grid_height_m"]
        )
        for r in rows
    }


def _fmt_geom(lat, lon, w, h) -> str:
    if None in (lat, lon, w, h):
        return "—"
    return f"({lat:.5f}, {lon:.5f}) {w / 1000:.1f}×{h / 1000:.1f} km"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--decisions",
        default=DEFAULT_DECISIONS,
        help="exported decisions CSV (default: audit/boundary_decisions.csv)",
    )
    parser.add_argument("--data-dir", default=get_default_data_dir())
    parser.add_argument(
        "--db-path", default=None, help="default: {data-dir}/streetscape_tracker.db"
    )
    parser.add_argument(
        "--execute", action="store_true", help="Apply changes (default is a dry run)"
    )
    parser.add_argument(
        "--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not os.path.exists(args.decisions):
        print(f"ERROR: decisions file not found: {args.decisions}", file=sys.stderr)
        return 2

    db_path = args.db_path or db.get_default_db_path(args.data_dir)
    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"=== Apply boundary decisions ({mode}) ===")
    print(f"Decisions: {args.decisions}")
    print(f"Catalog:   {db_path}\n")

    conn = db.connect(db_path)
    current_by_id = load_current_geometry(conn)

    with open(args.decisions, newline="") as f:
        plans = [
            plan_row(row, current_by_id.get(row.get("city_id", ""))) for row in csv.DictReader(f)
        ]

    apply = [p for p in plans if p.action == "APPLY"]
    nochange = [p for p in plans if p.action == "NOCHANGE"]
    skip = [p for p in plans if p.action == "SKIP"]

    for p in apply:
        print(f"  APPLY  {p.display_name} ({p.city_id})")
        print(
            f"         {_fmt_geom(p.old_center_lat, p.old_center_lon, p.old_width_m, p.old_height_m)}"
        )
        print(
            f"      ->  {_fmt_geom(p.new_center_lat, p.new_center_lon, p.new_width_m, p.new_height_m)}"
        )

    print(f"\nApply (recenter/resize): {len(apply)}")
    print(f"No change:               {len(nochange)}")
    print(f"Skipped:                 {len(skip)}")

    if not args.execute:
        print("\nDRY RUN — no catalog changes made. Re-run with --execute to apply.")
        conn.close()
        return 0

    for p in apply:
        db.update_city_geometry(
            conn,
            city_id=p.city_id,
            center_lat=p.new_center_lat,
            center_lon=p.new_center_lon,
            grid_width_m=p.new_width_m,
            grid_height_m=p.new_height_m,
            notes=APPLY_NOTE,
        )
    conn.close()
    print(f"\nApplied {len(apply)} boundary decisions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

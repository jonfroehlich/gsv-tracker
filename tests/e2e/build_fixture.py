"""Generate the committed synthetic frontend e2e fixture (issue #124).

Reuses the project's OWN summarizer + aggregate code (the same functions the
real pipeline runs), so the fixture tracks the live schema — aggregate v3, the
per-run JSON, the CSV column set — instead of drifting hand-authored JSON.

Re-run after any schema/format bump, then commit the regenerated files:

    python tests/e2e/build_fixture.py

Everything lands in ``tests/e2e/fixture/`` and is tiny enough to commit:

  * ``cities.json.gz``              aggregate schema v3, 3 cities
  * ``<city_id>_..._<date>.csv.gz`` + sibling ``.json.gz`` per run

The three cities cover the render paths the smoke test asserts on:

  * a normal multi-run **GSV** city  — snapshot ``<select>`` + change line
  * a **0-pano** GSV city (#69/#122) — "—" dates, no ``Infinity%``/``NaN``
  * a **Mapillary** city             — provider toggle / ``?provider=``

The catalog DB is built in a throwaway temp dir and discarded; only the gzipped
data artifacts are kept (mirrors the real publish glob, which excludes the DB).
"""

import os
import shutil
import sys
import tempfile
from datetime import date

# Make the repo root (and therefore ``tests`` and ``gsv_metadata_tracker``)
# importable when this script is run directly.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gsv_metadata_tracker import db  # noqa: E402
from gsv_metadata_tracker.fileutils import load_city_csv_file  # noqa: E402
from gsv_metadata_tracker.json_summarizer import (  # noqa: E402
    generate_aggregate_v2,
    generate_city_metadata_summary_as_json,
)
from tests.conftest import (  # noqa: E402
    make_city_df,
    make_mapillary_city_df,
    write_city_csv_gz,
)

# Not named "data/" on purpose: the repo .gitignore excludes any data/ dir, so
# a data/ subdir here would be silently un-committable.
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture")

# Shared frozen grid geometry for every fixture city (small, so files stay tiny).
W = H = 100
STEP = 20


def _run_name(city_id, run_date, provider="gsv"):
    """Filename for a run's csv.gz (gsv is tokenless, per naming.py)."""
    token = "" if provider == "gsv" else f"_{provider}"
    return f"{city_id}_width_{W}_height_{H}_step_{STEP}{token}_{run_date.isoformat()}.csv.gz"


def _write_summary(csv_path, city_name, state, country, run_date, provider="gsv"):
    """Write the per-run JSON summary next to the csv and return its path."""
    df = load_city_csv_file(csv_path)
    return generate_city_metadata_summary_as_json(
        csv_path,
        df,
        city_name,
        state,
        country,
        W,
        H,
        STEP,
        force_recreate_file=True,
        run_date=run_date,
        provider=provider,
    )


def _add_gsv_run(conn, city_id, city_name, state, country, panos, run_date, grid_origin, n_empty=1):
    name = _run_name(city_id, run_date)
    csv_path = os.path.join(FIXTURE_DIR, name)
    write_city_csv_gz(
        make_city_df(panos, run_date=run_date, grid_origin=grid_origin, n_empty=n_empty), csv_path
    )
    json_path = _write_summary(csv_path, city_name, state, country, run_date)
    return db.register_run(
        conn,
        city_id=city_id,
        run_date=run_date,
        csv_filename=name,
        json_filename=os.path.basename(json_path),
        unique_panos=len(panos),
        unique_google_panos=len(panos),
    )


def _add_mapillary_run(conn, city_id, city_name, state, country, panos, run_date, grid_origin):
    name = _run_name(city_id, run_date, provider="mapillary")
    csv_path = os.path.join(FIXTURE_DIR, name)
    write_city_csv_gz(
        make_mapillary_city_df(panos, run_date=run_date, grid_origin=grid_origin), csv_path
    )
    json_path = _write_summary(csv_path, city_name, state, country, run_date, provider="mapillary")
    return db.register_run(
        conn,
        city_id=city_id,
        run_date=run_date,
        csv_filename=name,
        provider="mapillary",
        json_filename=os.path.basename(json_path),
        unique_panos=len(panos),
    )


def _record_simple_diff(conn, city_id, from_run, to_run, added):
    """A minimal grid-aligned diff so the aggregate carries a 'change' block."""
    db.record_diff(
        conn,
        city_id=city_id,
        from_run_id=from_run,
        to_run_id=to_run,
        grid_aligned=True,
        panos_added=added,
        panos_removed=0,
        panos_persisted=1,
        capture_date_changed=0,
        points_gained_coverage=added,
        points_lost_coverage=0,
        coverage_delta_pct=25.0,
        detail_filename=None,
    )


def build():
    # Start from a clean fixture dir so re-runs are deterministic.
    if os.path.isdir(FIXTURE_DIR):
        shutil.rmtree(FIXTURE_DIR)
    os.makedirs(FIXTURE_DIR)

    # Keep the catalog DB out of the committed fixture (temp dir, discarded).
    db_tmp = tempfile.mkdtemp(prefix="gsv-e2e-db-")
    conn = db.connect(os.path.join(db_tmp, "gsv_tracker.db"))
    try:
        # 1) Normal multi-run GSV city: two runs, a diff, a spread of years.
        alpha = db.register_city(
            conn,
            city_name="Alpha City",
            state_name="Alphastate",
            state_code="AS",
            country_name="Testland",
            country_code="TL",
            center_lat=44.00,
            center_lon=-121.00,
            grid_width_m=W,
            grid_height_m=H,
            step_m=STEP,
        )
        r1 = _add_gsv_run(
            conn,
            alpha,
            "Alpha City",
            "Alphastate",
            "Testland",
            [("a1", "2018-06-01"), ("a2", "2020-06-01")],
            date(2026, 1, 15),
            grid_origin=(44.00, -121.00),
        )
        r2 = _add_gsv_run(
            conn,
            alpha,
            "Alpha City",
            "Alphastate",
            "Testland",
            [("a1", "2018-06-01"), ("a2", "2020-06-01"), ("a3", "2024-06-01")],
            date(2026, 4, 15),
            grid_origin=(44.00, -121.00),
        )
        _record_simple_diff(conn, alpha, r1, r2, added=1)

        # 2) 0-pano GSV city (#69/#122): a run with no panos at all.
        zero = db.register_city(
            conn,
            city_name="Zero City",
            state_name="Zerostate",
            state_code="ZS",
            country_name="Testland",
            country_code="TL",
            center_lat=45.00,
            center_lon=-120.00,
            grid_width_m=W,
            grid_height_m=H,
            step_m=STEP,
        )
        _add_gsv_run(
            conn,
            zero,
            "Zero City",
            "Zerostate",
            "Testland",
            [],
            date(2026, 4, 15),
            grid_origin=(45.00, -120.00),
            n_empty=3,
        )

        # 3) Mapillary city: one census run (drives the provider toggle).
        mapv = db.register_city(
            conn,
            city_name="Map Ville",
            state_name="Mapstate",
            state_code="MS",
            country_name="Testland",
            country_code="TL",
            center_lat=46.00,
            center_lon=-119.00,
            grid_width_m=W,
            grid_height_m=H,
            step_m=STEP,
        )
        _add_mapillary_run(
            conn,
            mapv,
            "Map Ville",
            "Mapstate",
            "Testland",
            [("m1", "2021-05-01"), ("m2", "2023-05-01")],
            date(2026, 4, 15),
            grid_origin=(46.00, -119.00),
        )

        # 4) Aggregate → cities.json.gz (schema v3) written into FIXTURE_DIR.
        summary = generate_aggregate_v2(conn, FIXTURE_DIR)
    finally:
        conn.close()
        shutil.rmtree(db_tmp, ignore_errors=True)

    files = sorted(os.listdir(FIXTURE_DIR))
    print(f"Wrote {len(files)} files to {FIXTURE_DIR} ({summary['cities_count']} cities):")
    for f in files:
        print(f"  {f}")
    return FIXTURE_DIR


if __name__ == "__main__":
    build()

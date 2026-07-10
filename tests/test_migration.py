"""Migration tests against a fixture mini data dir with an alias pair and a
NaN-corrupted JSON."""

import gzip
import json
import os
import subprocess
import sys
from datetime import date

from streetscape_metadata_tracker import db
from streetscape_metadata_tracker.fileutils import load_city_csv_file
from streetscape_metadata_tracker.json_summarizer import generate_city_metadata_summary_as_json
from tests.conftest import make_city_df, write_city_csv_gz

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "migrate_to_db.py")


def _make_legacy_city(
    data_dir,
    slug,
    city_name,
    state_name,
    country_name,
    panos,
    run_date,
    corrupt_json=False,
    width=100,
    height=100,
    step=20,
):
    """Create a legacy undated csv.gz + sibling json.gz pair."""
    base = f"{slug}_width_{width}_height_{height}_step_{step}"
    csv_path = os.path.join(data_dir, f"{base}.csv.gz")
    write_city_csv_gz(make_city_df(panos, run_date=run_date), csv_path)

    df = load_city_csv_file(csv_path)
    json_path = generate_city_metadata_summary_as_json(
        csv_path,
        df,
        city_name,
        state_name,
        country_name,
        width,
        height,
        step,
        force_recreate_file=True,
        run_date=run_date,
    )

    if corrupt_json:
        with gzip.open(json_path, "rt", encoding="utf-8") as f:
            text = f.read()
        text = text.replace('"stdev_pano_age_years": null', '"stdev_pano_age_years": NaN')
        assert "NaN" in text
        with gzip.open(json_path, "wt", encoding="utf-8") as f:
            f.write(text)
    return csv_path


def _run_migration(data_dir, *extra):
    return subprocess.run(
        [sys.executable, SCRIPT, "--data-dir", data_dir, "--no-nominatim", *extra],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


def test_migration_end_to_end(data_dir):
    # Alias pair: same city under two slugs (only content identity matters)
    _make_legacy_city(
        data_dir,
        "albany--ny",
        "Albany",
        "New York",
        "United States",
        [("p1", "2020-05-01")],
        date(2025, 1, 10),
    )
    _make_legacy_city(
        data_dir,
        "albany--new-york--united-states",
        "Albany",
        "New York",
        "United States",
        [("p1", "2020-05-01"), ("p2", "2021-05-01")],
        date(2025, 6, 10),
    )
    # Independent city with a single-pano NaN-corrupted JSON
    _make_legacy_city(
        data_dir,
        "solo--town",
        "Solo",
        None,
        "Testland",
        [("p9", "2019-03-01")],
        date(2025, 2, 2),
        corrupt_json=True,
    )

    # Dry run: no DB created
    result = _run_migration(data_dir)
    assert result.returncode == 0, result.stderr
    assert "Dry run complete" in result.stdout
    assert "albany--new-york--united-states  <-  albany--ny" in result.stdout
    assert not os.path.exists(os.path.join(data_dir, "streetscape_tracker.db"))

    # Execute
    result = _run_migration(data_dir, "--execute")
    assert result.returncode == 0, result.stderr

    conn = db.connect(os.path.join(data_dir, "streetscape_tracker.db"))
    cities = db.get_all_cities(conn)
    # 'solo--town' is a legacy slug; canonical id comes from the JSON identity
    assert {c.city_id for c in cities} == {"albany--new-york--united-states", "solo--testland"}

    # Alias resolves; canonical-slug file chosen as the baseline
    albany = db.resolve_city(conn, "albany--ny")
    assert albany.city_id == "albany--new-york--united-states"
    run = db.get_latest_run(conn, albany.city_id)
    assert run.is_baseline
    assert run.csv_filename.startswith("albany--new-york--united-states_")
    assert run.run_date == "2025-06-10"
    assert run.unique_panos == 2

    # Corrupt JSON was regenerated as strict-parseable
    solo_run = db.get_latest_run(conn, "solo--testland")
    with gzip.open(os.path.join(data_dir, solo_run.json_filename), "rt") as f:
        json.load(f, parse_constant=lambda t: (_ for _ in ()).throw(ValueError(t)))

    # Idempotent: re-running registers nothing new
    result = _run_migration(data_dir, "--execute")
    assert result.returncode == 0, result.stderr
    assert "Registered 0 cities, 0 baseline runs" in result.stdout
    conn.close()

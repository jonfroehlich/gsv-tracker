"""
Tests for map-visualization edge cases (gsv_metadata_tracker/vis.py).

Pure-logic / no-network: these build a tiny in-memory metadata DataFrame and
call create_visualization_map, asserting it produces a folium.Map without
raising. The focus is the degenerate-geometry guard from issue #69.
"""

import folium
import pandas as pd

from gsv_metadata_tracker import vis
from gsv_metadata_tracker.config import METADATA_DTYPES


def _row(pano_id, lat, lon):
    """One valid, official-Google GSV metadata row (config.METADATA_DTYPES)."""
    return {
        "query_lat": lat,
        "query_lon": lon,
        "query_timestamp": "2026-07-01T00:00:00+00:00",
        "pano_lat": lat,
        "pano_lon": lon,
        "pano_id": pano_id,
        "capture_date": "2024-08-01",
        "copyright_info": "© Google",
        "status": "OK",
    }


def _frame(rows):
    df = pd.DataFrame(rows, columns=list(METADATA_DTYPES.keys()))
    return df.astype({"pano_id": "string", "copyright_info": "string"})


def test_single_pano_city_does_not_crash():
    """
    A city with exactly one valid pano yields a 0 x 0 bounding box, so the
    coverage-density division would raise ZeroDivisionError without the guard
    (issue #69 — e.g. Eastsound, WA / Kodiak, AK). It must return a map instead.
    """
    result = vis.create_visualization_map(_frame([_row("p1", 47.62, -122.35)]), "Eastsound, WA")
    assert isinstance(result, folium.Map)


def test_no_valid_panos_returns_empty_map():
    """Zero valid rows is already guarded and returns an empty map, not a crash."""
    row = _row("p1", 47.62, -122.35)
    row["status"] = "ZERO_RESULTS"  # filtered out -> no valid rows
    result = vis.create_visualization_map(_frame([row]), "Nowhere, WA")
    assert isinstance(result, folium.Map)


def test_multi_pano_city_still_builds():
    """A normal multi-pano city (non-zero area) is unaffected by the guard."""
    rows = [_row("p1", 47.60, -122.33), _row("p2", 47.62, -122.35), _row("p3", 47.64, -122.31)]
    result = vis.create_visualization_map(_frame(rows), "Seattle, WA")
    assert isinstance(result, folium.Map)

"""Unit tests for fractional per-edge road-walk coverage (issue #99).

Builds edges + samples + a synthetic collected DataFrame by hand (no network)
and checks the fraction arithmetic, the sample-to-pano distance guard, the
official-Google filter, and JSON validity of the coverage artifact.
"""

import json

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from streetscape_street_analyzer import road_sampling as rs
from streetscape_street_analyzer import street_coverage as sc

LONG_EDGE = LineString([(-121.30, 44.05), (-121.30, 44.052)])
SHORT_EDGE = LineString([(-121.30, 44.052), (-121.30, 44.0525)])
RUN_DATE = "2026-07-08"


def _edges():
    return gpd.GeoDataFrame(
        {"edge_id": ["1_2", "2_3"], "highway": ["residential", "service"], "length": [222.0, 55.0]},
        geometry=[LONG_EDGE, SHORT_EDGE],
        crs="EPSG:4326",
    )


def _collected(samples, covered_pred, *, pano_offset=0.0, copyright_="© Google", date="2022-06-01"):
    """Synthesize a METADATA-shaped collected frame from the sample list.

    `covered_pred(row)` decides whether a sample gets an OK pano; `pano_offset`
    shifts the returned pano's latitude (to exercise the distance guard).
    """
    rows = []
    for r in samples.itertuples():
        cov = covered_pred(r)
        rows.append(
            {
                "query_lat": r.lat,
                "query_lon": r.lon,
                "pano_lat": (r.lat + pano_offset) if cov else None,
                "pano_lon": r.lon if cov else None,
                "pano_id": ("p" if cov else None),
                "capture_date": (date if cov else None),
                "copyright_info": (copyright_ if cov else None),
                "status": ("OK" if cov else "ZERO_RESULTS"),
                "query_timestamp": "2026-07-08T00:00:00Z",
            }
        )
    return pd.DataFrame(rows)


def test_fractional_coverage_per_edge():
    edges = _edges()
    samples = rs.generate_samples(edges, spacing_m=15.0)
    # Cover the first 8 of edge 1_2's 15 samples; none of edge 2_3.
    collected = _collected(samples, lambda r: r.edge_id == "1_2" and r.sample_idx < 8)
    out = sc.compute_streetwalk_coverage(edges, samples, collected, RUN_DATE, "gsv", 25.0)
    by_edge = out.set_index("edge_id")
    assert by_edge.loc["1_2", "total_samples"] == 15
    assert by_edge.loc["1_2", "covered_samples"] == 8
    assert round(by_edge.loc["1_2", "coverage_fraction"], 4) == round(8 / 15, 4)
    assert by_edge.loc["1_2", "covered"]
    assert by_edge.loc["2_3", "covered_samples"] == 0
    assert not by_edge.loc["2_3", "covered"]


def test_distance_guard_rejects_far_pano():
    edges = _edges()
    samples = rs.generate_samples(edges, spacing_m=15.0)
    # Every sample gets an OK Google pano, but ~222 m north (>> 25 m threshold).
    collected = _collected(samples, lambda r: True, pano_offset=0.002)
    out = sc.compute_streetwalk_coverage(edges, samples, collected, RUN_DATE, "gsv", 25.0)
    assert int(out["covered_samples"].sum()) == 0


def test_non_google_copyright_excluded_for_gsv():
    edges = _edges()
    samples = rs.generate_samples(edges, spacing_m=15.0)
    collected = _collected(samples, lambda r: True, copyright_="© Someone Else")
    out = sc.compute_streetwalk_coverage(edges, samples, collected, RUN_DATE, "gsv", 25.0)
    assert int(out["covered_samples"].sum()) == 0


def test_non_gsv_provider_keeps_any_ok_pano():
    edges = _edges()
    samples = rs.generate_samples(edges, spacing_m=15.0)
    collected = _collected(samples, lambda r: True, copyright_=None)
    out = sc.compute_streetwalk_coverage(edges, samples, collected, RUN_DATE, "mapillary", 25.0)
    assert int(out["covered_samples"].sum()) == len(samples)


def test_geojson_is_strictly_valid_and_carries_metadata():
    edges = _edges()
    samples = rs.generate_samples(edges, spacing_m=15.0)
    collected = _collected(samples, lambda r: r.edge_id == "1_2" and r.sample_idx < 8)
    out = sc.compute_streetwalk_coverage(edges, samples, collected, RUN_DATE, "gsv", 25.0)
    gj = sc.build_streetwalk_geojson(
        out,
        city_id="bend--or",
        provider="gsv",
        run_date=RUN_DATE,
        spacing_m=15.0,
        match_dist_m=25.0,
        source_csv="x.csv.gz",
    )
    # allow_nan=False raises on any NaN — uncovered edges must serialize None.
    json.dumps(gj, allow_nan=False)
    meta = gj["properties"]["metadata"]
    assert meta["kind"] == "streetwalk_coverage"
    assert meta["spacing_m"] == 15.0
    totals = meta["totals"]
    assert totals["edges"] == 2
    assert totals["edges_fully_covered"] == 0
    assert 0.0 < totals["mean_edge_coverage"] < 1.0
    # One uncovered edge feature must have null date/age (not NaN).
    uncovered = [f for f in gj["features"] if f["properties"]["edge_id"] == "2_3"][0]
    assert uncovered["properties"]["nearest_pano_date"] is None
    assert uncovered["properties"]["median_covered_age_years"] is None


def test_empty_edges_yield_zero_edge_frame():
    edges = _edges().iloc[0:0]
    samples = rs.generate_samples(_edges(), spacing_m=15.0).iloc[0:0]
    out = sc.compute_streetwalk_coverage(edges, samples, pd.DataFrame(), RUN_DATE, "gsv", 25.0)
    assert len(out) == 0
    assert "coverage_fraction" in out.columns

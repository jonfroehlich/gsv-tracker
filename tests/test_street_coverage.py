"""
Street-coverage analysis tests (no network).

Exercises the pure-logic core in gsv_street_analyzer.street_coverage with
hand-built street-edge and pano geometries. The OSM/Overpass fetch in
download_street_network is deliberately not touched here.

Geometry trick for predictable metre distances: streets run east-west along a
constant latitude, and panos are offset purely in latitude. One degree of
latitude is ~111320 m everywhere, so a pano offset by ``dlat`` degrees sits
~111320*dlat m from the street regardless of the UTM zone the code projects to.
"""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from gsv_street_analyzer.street_coverage import (
    build_streets_geojson,
    compute_street_coverage,
    normalize_highway,
    select_pano_points,
    summarize_coverage,
)

LAT0 = 47.6062
LON0 = -122.3321
M_PER_DEG_LAT = 111320.0
RUN_DATE = "2026-07-01"


def _dlat_for_metres(metres):
    return metres / M_PER_DEG_LAT


def _make_edges(specs):
    """specs: list of (highway, extra_props). Each edge is a ~78 m E-W segment."""
    rows = []
    geoms = []
    for i, (highway, _length_hint) in enumerate(specs):
        lat = LAT0 + i * 0.01  # separate edges so they don't share panos
        geoms.append(LineString([(LON0, lat), (LON0 + 0.001, lat)]))
        rows.append({"highway": highway})
    return gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")


def _pano_gdf(points):
    """points: list of (lon, lat, capture_date_str_or_None)."""
    caps = pd.to_datetime([p[2] for p in points])
    geom = [Point(p[0], p[1]) for p in points]
    return gpd.GeoDataFrame({"capture_date": caps}, geometry=geom, crs="EPSG:4326")


# ── normalize_highway ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("residential", "residential"),
        ("motorway_link", "motorway"),
        (["primary", "residential"], "primary"),
        (["unknownclass", "secondary"], "secondary"),
        ("footway", "other"),
        (None, "other"),
        ([], "other"),
    ],
)
def test_normalize_highway(raw, expected):
    assert normalize_highway(raw) == expected


# ── coverage matching ────────────────────────────────────────────────────────

def test_covered_vs_uncovered_at_threshold():
    edges = _make_edges([("residential", None), ("residential", None)])
    # Edge 0 at LAT0: near pano (~11 m). Edge 1 at LAT0+0.01: far pano (~56 m).
    panos = _pano_gdf([
        (LON0 + 0.0005, LAT0 + _dlat_for_metres(11), "2024-01-01"),
        (LON0 + 0.0005, LAT0 + 0.01 + _dlat_for_metres(56), "2024-01-01"),
    ])
    out = compute_street_coverage(edges, panos, RUN_DATE, match_dist_m=25.0)
    assert list(out["covered"]) == [True, False]
    # length_m is derived (~78 m for a 0.001deg E-W segment at this latitude)
    assert 70 < out["length_m"].iloc[0] < 85


def test_no_panos_all_uncovered():
    edges = _make_edges([("primary", None)])
    empty = gpd.GeoDataFrame({"capture_date": pd.to_datetime([])},
                             geometry=[], crs="EPSG:4326")
    out = compute_street_coverage(edges, empty, RUN_DATE)
    assert not out["covered"].any()
    assert out["nearest_pano_date"].iloc[0] is None


def test_age_pinned_to_run_date():
    edges = _make_edges([("residential", None)])
    panos = _pano_gdf([(LON0 + 0.0005, LAT0 + _dlat_for_metres(5), "2024-07-01")])
    out = compute_street_coverage(edges, panos, RUN_DATE, match_dist_m=25.0)
    assert out["covered"].iloc[0]
    assert out["nearest_pano_date"].iloc[0] == "2024-07-01"
    # 2024-07-01 -> 2026-07-01 is ~2.0 years (pinned to run_date, not "now")
    assert out["nearest_pano_age_years"].iloc[0] == pytest.approx(2.0, abs=0.01)


def test_covered_pano_without_date():
    edges = _make_edges([("residential", None)])
    panos = _pano_gdf([(LON0 + 0.0005, LAT0 + _dlat_for_metres(5), None)])
    out = compute_street_coverage(edges, panos, RUN_DATE, match_dist_m=25.0)
    assert out["covered"].iloc[0]  # covered even though the date is unknown
    assert out["nearest_pano_date"].iloc[0] is None
    assert out["nearest_pano_age_years"].iloc[0] is None


# ── aggregation ──────────────────────────────────────────────────────────────

def test_summary_by_count_vs_length_diverge():
    # 3 short residential edges (2 covered) + 1 long motorway edge (uncovered).
    edges = _make_edges([
        ("residential", None),
        ("residential", None),
        ("residential", None),
        ("motorway", None),
    ])
    # Make the motorway long so length- and count-based coverage disagree.
    edges.loc[3, "geometry"] = LineString(
        [(LON0, LAT0 + 0.03), (LON0 + 0.05, LAT0 + 0.03)]
    )
    panos = _pano_gdf([
        (LON0 + 0.0005, LAT0 + _dlat_for_metres(5), "2024-01-01"),
        (LON0 + 0.0005, LAT0 + 0.01 + _dlat_for_metres(5), "2024-01-01"),
        # edge 2 (residential) and edge 3 (motorway) left uncovered
    ])
    out = compute_street_coverage(edges, panos, RUN_DATE, match_dist_m=25.0)
    summary = summarize_coverage(out)

    res = summary["coverage_by_highway"]["residential"]
    assert res["segments"] == 3 and res["covered"] == 2
    assert res["coverage_pct_by_count"] == pytest.approx(66.7, abs=0.1)

    mot = summary["coverage_by_highway"]["motorway"]
    assert mot["segments"] == 1 and mot["covered"] == 0

    totals = summary["totals"]
    assert totals["segments"] == 4 and totals["covered"] == 2
    assert totals["coverage_pct_by_count"] == pytest.approx(50.0, abs=0.1)
    # By length the long uncovered motorway dominates -> far below 50%.
    assert totals["coverage_pct_by_length"] < totals["coverage_pct_by_count"]
    assert totals["uncovered_pct_by_length"] == pytest.approx(
        100 - totals["coverage_pct_by_length"], abs=0.1
    )
    # buckets ordered by road hierarchy: motorway before residential
    assert list(summary["coverage_by_highway"]) == ["motorway", "residential"]


# ── provider-specific pano selection ─────────────────────────────────────────

def _run_df(rows):
    return pd.DataFrame(rows, columns=[
        "status", "pano_lat", "pano_lon", "capture_date", "copyright_info",
    ])


def test_select_pano_points_gsv_google_only():
    df = _run_df([
        ("OK", LAT0, LON0, "2024-01-01", "© Google"),        # kept
        ("OK", LAT0, LON0, "2024-01-01", "© Someone Google"),  # dropped (not exact)
        ("OK", LAT0, LON0, "2024-01-01", None),               # dropped (no copyright)
        ("ZERO_RESULTS", None, None, None, None),             # dropped (no pano)
        ("OK", None, None, "2024-01-01", "© Google"),         # dropped (no coords)
    ])
    pts = select_pano_points(df, "gsv")
    assert len(pts) == 1


def test_select_pano_points_mapillary_keeps_all_located():
    df = _run_df([
        ("OK", LAT0, LON0, "2024-01-01", "someuser"),
        ("OK", LAT0, LON0, None, "otheruser"),
        ("ZERO_RESULTS", None, None, None, None),  # dropped (no pano)
    ])
    pts = select_pano_points(df, "mapillary")
    assert len(pts) == 2


# ── GeoJSON artifact shape ───────────────────────────────────────────────────

def test_build_geojson_structure():
    edges = _make_edges([("residential", None), ("primary", None)])
    panos = _pano_gdf([(LON0 + 0.0005, LAT0 + _dlat_for_metres(5), "2024-01-01")])
    out = compute_street_coverage(edges, panos, RUN_DATE, match_dist_m=25.0)
    fc = build_streets_geojson(
        out, city_id="test--city", provider="gsv", run_date=RUN_DATE,
        match_dist_m=25.0, source_csv="test--city_..._2026-07-01.csv.gz",
    )
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    meta = fc["properties"]["metadata"]
    assert meta["kind"] == "street_coverage" and meta["provider"] == "gsv"
    assert meta["totals"]["segments"] == 2
    feat = fc["features"][0]
    assert feat["geometry"]["type"] == "LineString"
    assert set(feat["properties"]) == {
        "highway", "length_m", "covered", "nearest_pano_date",
        "nearest_pano_age_years",
    }

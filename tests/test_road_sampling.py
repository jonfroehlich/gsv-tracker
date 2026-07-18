"""Unit tests for on-street sample-point generation (issue #99).

Pure geometry — no network, no provider. Builds edges by hand and checks the
sample counts, spacing bounds, determinism, and query-point de-duplication that
the road-walk collector relies on.
"""

import geopandas as gpd
from shapely.geometry import LineString

from streetscape_street_analyzer.road_sampling import (
    dedupe_query_points,
    generate_samples,
    quantize_coord,
)

# A ~222 m N-S segment (0.002° latitude) and a ~55 m one, near Bend, OR.
LONG_EDGE = LineString([(-121.30, 44.05), (-121.30, 44.052)])
SHORT_EDGE = LineString([(-121.30, 44.052), (-121.30, 44.0525)])


def _edges():
    return gpd.GeoDataFrame(
        {"edge_id": ["1_2", "2_3"], "highway": ["residential", "service"]},
        geometry=[LONG_EDGE, SHORT_EDGE],
        crs="EPSG:4326",
    )


def test_sample_counts_track_edge_length():
    samples = generate_samples(_edges(), spacing_m=15.0)
    counts = samples.groupby("edge_id").size().to_dict()
    # ~222 m / 15 ≈ 15; ~55 m / 15 ≈ 4 (round(L/spacing)).
    assert counts["1_2"] == 15
    assert counts["2_3"] == 4
    assert list(samples.columns) == ["edge_id", "sample_idx", "lat", "lon"]


def test_every_edge_gets_at_least_its_midpoint():
    # A tiny edge far shorter than the spacing still gets one (centered) sample.
    tiny = gpd.GeoDataFrame(
        {"edge_id": ["x"], "highway": ["service"]},
        geometry=[LineString([(-121.30, 44.05), (-121.30, 44.0500005)])],
        crs="EPSG:4326",
    )
    samples = generate_samples(tiny, spacing_m=15.0)
    assert len(samples) == 1
    assert samples.iloc[0]["sample_idx"] == 0


def test_actual_spacing_within_bounds():
    # Points are evenly spaced and centered, so along-edge spacing stays within
    # [spacing/2, spacing]. Check the long edge's samples in metric space.
    edges = _edges()
    samples = generate_samples(edges, spacing_m=15.0)
    long_pts = samples[samples["edge_id"] == "1_2"].reset_index(drop=True)
    metric = gpd.GeoSeries(
        gpd.points_from_xy(long_pts["lon"], long_pts["lat"]), crs="EPSG:4326"
    ).to_crs(edges.estimate_utm_crs())
    gaps = [metric.iloc[i].distance(metric.iloc[i + 1]) for i in range(len(metric) - 1)]
    assert all(7.4 <= g <= 15.1 for g in gaps), gaps


def test_deterministic():
    a = generate_samples(_edges(), spacing_m=15.0)
    b = generate_samples(_edges(), spacing_m=15.0)
    assert a.equals(b)


def test_empty_edges_yield_empty_frame():
    empty = _edges().iloc[0:0]
    samples = generate_samples(empty, spacing_m=15.0)
    assert len(samples) == 0
    assert list(samples.columns) == ["edge_id", "sample_idx", "lat", "lon"]


def test_invalid_spacing_raises():
    import pytest

    with pytest.raises(ValueError):
        generate_samples(_edges(), spacing_m=0)


def test_dedupe_collapses_shared_locations():
    import pandas as pd

    samples = generate_samples(_edges(), spacing_m=15.0)
    # Duplicate every row: dedupe must collapse back to the unique locations.
    doubled = pd.concat([samples, samples], ignore_index=True)
    points = dedupe_query_points(doubled)
    assert len(points) == len(samples)
    # Tuples are (lat, lon, seq, 0); seq is a running index.
    assert [p[2] for p in points] == list(range(len(points)))
    assert all(p[3] == 0 for p in points)


def test_quantize_coord_rounds_to_nine_decimals():
    assert quantize_coord(44.0500000001, -121.3000000004) == (44.05, -121.3)

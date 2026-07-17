"""
Street-coverage analysis tests (no network).

Exercises the pure-logic core in streetscape_street_analyzer.street_coverage with
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

from streetscape_street_analyzer.street_coverage import (
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
    panos = _pano_gdf(
        [
            (LON0 + 0.0005, LAT0 + _dlat_for_metres(11), "2024-01-01"),
            (LON0 + 0.0005, LAT0 + 0.01 + _dlat_for_metres(56), "2024-01-01"),
        ]
    )
    out = compute_street_coverage(edges, panos, RUN_DATE, match_dist_m=25.0)
    assert list(out["covered"]) == [True, False]
    # length_m is derived (~78 m for a 0.001deg E-W segment at this latitude)
    assert 70 < out["length_m"].iloc[0] < 85


def test_no_panos_all_uncovered():
    edges = _make_edges([("primary", None)])
    empty = gpd.GeoDataFrame({"capture_date": pd.to_datetime([])}, geometry=[], crs="EPSG:4326")
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
    edges = _make_edges(
        [
            ("residential", None),
            ("residential", None),
            ("residential", None),
            ("motorway", None),
        ]
    )
    # Make the motorway long so length- and count-based coverage disagree.
    edges.loc[3, "geometry"] = LineString([(LON0, LAT0 + 0.03), (LON0 + 0.05, LAT0 + 0.03)])
    panos = _pano_gdf(
        [
            (LON0 + 0.0005, LAT0 + _dlat_for_metres(5), "2024-01-01"),
            (LON0 + 0.0005, LAT0 + 0.01 + _dlat_for_metres(5), "2024-01-01"),
            # edge 2 (residential) and edge 3 (motorway) left uncovered
        ]
    )
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
    return pd.DataFrame(
        rows,
        columns=[
            "status",
            "pano_lat",
            "pano_lon",
            "capture_date",
            "copyright_info",
        ],
    )


def test_select_pano_points_gsv_google_only():
    df = _run_df(
        [
            ("OK", LAT0, LON0, "2024-01-01", "© Google"),  # kept
            ("OK", LAT0, LON0, "2024-01-01", "© Someone Google"),  # dropped (not exact)
            ("OK", LAT0, LON0, "2024-01-01", None),  # dropped (no copyright)
            ("ZERO_RESULTS", None, None, None, None),  # dropped (no pano)
            ("OK", None, None, "2024-01-01", "© Google"),  # dropped (no coords)
        ]
    )
    pts = select_pano_points(df, "gsv")
    assert len(pts) == 1


def test_select_pano_points_gsv_missing_copyright_column():
    """A legacy pre-copyright baseline CSV may lack the copyright_info column
    entirely. GSV selection must treat that as 'no official Google imagery'
    (empty result) rather than raising KeyError."""
    df = _run_df(
        [
            ("OK", LAT0, LON0, "2024-01-01", "© Google"),
            ("OK", LAT0, LON0, "2024-01-01", "© Google"),
        ]
    ).drop(columns=["copyright_info"])
    pts = select_pano_points(df, "gsv")
    assert len(pts) == 0


def test_select_pano_points_mapillary_keeps_all_located():
    df = _run_df(
        [
            ("OK", LAT0, LON0, "2024-01-01", "someuser"),
            ("OK", LAT0, LON0, None, "otheruser"),
            ("ZERO_RESULTS", None, None, None, None),  # dropped (no pano)
        ]
    )
    pts = select_pano_points(df, "mapillary")
    assert len(pts) == 2


# ── GeoJSON artifact shape ───────────────────────────────────────────────────


def test_build_geojson_structure():
    edges = _make_edges([("residential", None), ("primary", None)])
    panos = _pano_gdf([(LON0 + 0.0005, LAT0 + _dlat_for_metres(5), "2024-01-01")])
    out = compute_street_coverage(edges, panos, RUN_DATE, match_dist_m=25.0)
    fc = build_streets_geojson(
        out,
        city_id="test--city",
        provider="gsv",
        run_date=RUN_DATE,
        match_dist_m=25.0,
        source_csv="test--city_..._2026-07-01.csv.gz",
    )
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    meta = fc["properties"]["metadata"]
    assert meta["kind"] == "street_coverage" and meta["provider"] == "gsv"
    assert meta["totals"]["segments"] == 2
    feat = fc["features"][0]
    assert feat["geometry"]["type"] == "LineString"
    assert set(feat["properties"]) == {
        "highway",
        "length_m",
        "covered",
        "nearest_pano_date",
        "nearest_pano_age_years",
    }


# ── Frozen-network catalog registration (issue #103, no network) ────────────


def test_fetch_graph_cache_hit_backfills_catalog(tmp_path, monkeypatch):
    """Loading a pre-existing GraphML cache registers a missing catalog row
    (adopting caches created before street_networks existed), and a second
    load leaves the row untouched — no duplicates, no re-registration."""
    import networkx as nx
    import osmnx as ox

    from streetscape_metadata_tracker import db
    from streetscape_street_analyzer.download_street_network import fetch_graph

    data_dir = str(tmp_path)
    conn = db.connect(str(tmp_path / "catalog.db"))
    city_id = db.register_city(
        conn,
        city_name="Bend",
        state_name="Oregon",
        state_code="OR",
        country_name="United States",
        country_code="US",
        center_lat=44.05,
        center_lon=-121.31,
        grid_width_m=5000,
        grid_height_m=5000,
        step_m=20,
    )
    city = db.resolve_city(conn, city_id)

    fake_graph = nx.MultiDiGraph()
    fake_graph.add_edge(1, 2)
    cache = tmp_path / "osm_cache" / f"{city_id}_streets_network.graphml"
    cache.parent.mkdir()
    cache.touch()  # only existence is checked; the load is monkeypatched
    monkeypatch.setattr(ox, "load_graphml", lambda path: fake_graph)

    graph = fetch_graph(city, data_dir, conn=conn)
    assert graph is fake_graph
    row = db.get_street_network(conn, city_id)
    assert row["graphml_filename"] == f"{city_id}_streets_network.graphml"
    assert (row["node_count"], row["edge_count"]) == (2, 1)
    assert row["osmnx_version"] == ox.__version__

    first_fetched_at = row["fetched_at"]
    fetch_graph(city, data_dir, conn=conn)  # second load: row already present
    again = db.get_street_network(conn, city_id)
    assert again["fetched_at"] == first_fetched_at
    conn.close()


def test_fetch_graph_without_conn_skips_catalog(tmp_path, monkeypatch):
    import networkx as nx
    import osmnx as ox

    from streetscape_metadata_tracker.db import CityRow
    from streetscape_street_analyzer.download_street_network import fetch_graph

    city = CityRow(
        city_id="bend--or",
        display_name="Bend, OR",
        city_name="Bend",
        state_name="Oregon",
        state_code="OR",
        country_name="United States",
        country_code="US",
        center_lat=44.05,
        center_lon=-121.31,
        grid_width_m=5000,
        grid_height_m=5000,
        step_m=20,
        created_at="2026-01-01T00:00:00+00:00",
        enabled=True,
        notes=None,
    )
    cache = tmp_path / "osm_cache" / "bend--or_streets_network.graphml"
    cache.parent.mkdir()
    cache.touch()
    monkeypatch.setattr(ox, "load_graphml", lambda path: nx.MultiDiGraph())
    fetch_graph(city, str(tmp_path))  # must not raise without a catalog


def _fake_city(city_id="bend--or"):
    from streetscape_metadata_tracker.db import CityRow

    return CityRow(
        city_id=city_id,
        display_name="Bend, OR",
        city_name="Bend",
        state_name="Oregon",
        state_code="OR",
        country_name="United States",
        country_code="US",
        center_lat=44.05,
        center_lon=-121.31,
        grid_width_m=5000,
        grid_height_m=5000,
        step_m=20,
        created_at="2026-01-01T00:00:00+00:00",
        enabled=True,
        notes=None,
    )


def test_fetch_graph_download_registers_and_refresh_replaces(tmp_path, monkeypatch):
    """A fresh download saves the GraphML and registers the catalog row;
    --refresh re-downloads and REPLACES the row (counts updated, still one
    row) rather than erroring or appending."""
    import networkx as nx

    from streetscape_metadata_tracker import db
    from streetscape_street_analyzer import download_street_network as dsn

    conn = db.connect(str(tmp_path / "catalog.db"))
    city_id = db.register_city(
        conn,
        city_name="Bend",
        state_name="Oregon",
        state_code="OR",
        country_name="United States",
        country_code="US",
        center_lat=44.05,
        center_lon=-121.31,
        grid_width_m=5000,
        grid_height_m=5000,
        step_m=20,
    )
    city = db.resolve_city(conn, city_id)

    def fake_graph(n_edges):
        g = nx.MultiDiGraph()
        for i in range(n_edges):
            g.add_edge(i, i + 1)
        return g

    downloads = []

    def fake_download(bbox, network_type):
        downloads.append(bbox)
        return fake_graph(3 if len(downloads) == 1 else 7)

    monkeypatch.setattr(dsn, "_download_graph", fake_download)
    monkeypatch.setattr(dsn.ox, "save_graphml", lambda g, p: open(p, "w").close())

    dsn.fetch_graph(city, str(tmp_path), conn=conn)
    row = db.get_street_network(conn, city_id)
    assert row["edge_count"] == 3
    assert (tmp_path / "osm_cache" / f"{city_id}_streets_network.graphml").exists()

    # Cache now exists: a plain call must NOT re-download...
    monkeypatch.setattr(dsn.ox, "load_graphml", lambda p: fake_graph(3))
    dsn.fetch_graph(city, str(tmp_path), conn=conn)
    assert len(downloads) == 1

    # ...but refresh=True re-downloads and replaces the single catalog row.
    dsn.fetch_graph(city, str(tmp_path), conn=conn, refresh=True)
    assert len(downloads) == 2
    row = db.get_street_network(conn, city_id)
    assert row["edge_count"] == 7
    assert conn.execute("SELECT COUNT(*) FROM street_networks").fetchone()[0] == 1
    conn.close()


def test_network_cache_filename_types():
    from streetscape_street_analyzer.download_street_network import network_cache_filename

    # The default drive network keeps the original un-suffixed name so caches
    # (and catalog rows) predating network_type stay valid.
    assert network_cache_filename("bend--or") == "bend--or_streets_network.graphml"
    assert network_cache_filename("bend--or", "drive") == "bend--or_streets_network.graphml"
    assert network_cache_filename("bend--or", "walk") == "bend--or_streets_network_walk.graphml"


def test_graph_to_edges_collapses_reciprocal_edges():
    """osmnx returns both directions of a two-way street, and orients each
    directed edge's geometry in its own travel direction — so the reciprocal
    edge's LineString is coordinate-REVERSED. graph_to_edges must still collapse
    the pair to one row (by unordered node pair, not geometry WKB) so segments
    aren't double-counted."""
    import networkx as nx

    from streetscape_street_analyzer.download_street_network import graph_to_edges

    g = nx.MultiDiGraph(crs="EPSG:4326")
    g.add_node(1, x=-121.310, y=44.050)
    g.add_node(2, x=-121.309, y=44.050)
    g.add_node(3, x=-121.308, y=44.050)
    forward = LineString([(-121.310, 44.050), (-121.309, 44.050)])
    reverse = LineString([(-121.309, 44.050), (-121.310, 44.050)])  # osmnx reverses it
    g.add_edge(1, 2, highway="residential", length=80.0, geometry=forward)
    g.add_edge(2, 1, highway="residential", length=80.0, geometry=reverse)  # reciprocal
    g.add_edge(
        2,
        3,
        highway="service",
        length=80.0,
        geometry=LineString([(-121.309, 44.050), (-121.308, 44.050)]),
    )

    edges = graph_to_edges(g)
    assert len(edges) == 2  # 3 directed edges -> 2 unique segments
    assert sorted(edges["highway"]) == ["residential", "service"]

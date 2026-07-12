"""
Mapillary downloader tests: tile math, MVT decoding, pano filtering, date
handling, grid assignment, and an end-to-end download with synthetic tiles
served from memory. No network.
"""

import asyncio
import gzip
import math
import re
from datetime import UTC, datetime

import geopy
import mapbox_vector_tile
import numpy as np
import pandas as pd
import pytest

from streetscape_metadata_tracker import download_mapillary as dm
from streetscape_metadata_tracker.config import METADATA_DTYPES
from streetscape_metadata_tracker.download_common import generate_grid_points

SEATTLE = (47.6062, -122.3321)


# ── Tile math ──────────────────────────────────────────────────────────────


def test_tile_frac_known_anchors():
    n = 2**14
    # Greenwich/equator sits exactly at the center of the tile grid
    fx, fy = dm.lonlat_to_tile_frac(0.0, 0.0, 14)
    assert fx == pytest.approx(n / 2)
    assert fy == pytest.approx(n / 2)
    # Antimeridian west edge is tile x=0
    fx, _ = dm.lonlat_to_tile_frac(-180.0, 0.0, 14)
    assert fx == pytest.approx(0.0)


@pytest.mark.parametrize(
    "lon,lat",
    [
        (0.0, 0.0),
        (-122.3321, 47.6062),  # Seattle
        (151.2093, -33.8688),  # Sydney (southern hemisphere)
        (18.9553, 69.6496),  # Tromsø (high latitude)
    ],
)
def test_tile_frac_roundtrip(lon, lat):
    fx, fy = dm.lonlat_to_tile_frac(lon, lat, 14)
    lon2, lat2 = dm.tile_frac_to_lonlat(fx, fy, 14)
    assert lon2 == pytest.approx(lon, abs=1e-9)
    assert lat2 == pytest.approx(lat, abs=1e-9)


def test_tiles_for_bbox_single_tile():
    # A bbox strictly inside one tile yields exactly that tile
    fx, fy = dm.lonlat_to_tile_frac(*reversed(SEATTLE), 14)
    lon_mid, lat_mid = dm.tile_frac_to_lonlat(int(fx) + 0.5, int(fy) + 0.5, 14)
    eps = 1e-5
    tiles = dm.tiles_for_bbox(lon_mid - eps, lat_mid - eps, lon_mid + eps, lat_mid + eps)
    assert tiles == [(int(fx), int(fy))]


def test_tiles_for_bbox_straddles_boundary():
    # A bbox centered on a tile corner touches all four neighbors
    fx, fy = dm.lonlat_to_tile_frac(*reversed(SEATTLE), 14)
    x0, y0 = int(fx), int(fy)
    corner_lon, corner_lat = dm.tile_frac_to_lonlat(x0, y0, 14)
    eps = 1e-5
    tiles = set(
        dm.tiles_for_bbox(corner_lon - eps, corner_lat - eps, corner_lon + eps, corner_lat + eps)
    )
    assert tiles == {(x0 - 1, y0 - 1), (x0, y0 - 1), (x0 - 1, y0), (x0, y0)}


def test_tiles_for_bbox_wraps_across_antimeridian():
    # A grid straddling 180° (e.g. Suva, Fiji region) arrives with
    # min_lon > max_lon after geopy normalizes longitudes to ±180. The
    # tile list must wrap and cover columns on BOTH sides of the seam —
    # the naive single x-range was empty, silently yielding a 0-tile run.
    tiles = dm.tiles_for_bbox(179.98, -18.2, -179.98, -18.1, zoom=14)
    assert tiles
    xs = {x for x, _ in tiles}
    n = 2**14
    assert (n - 1) in xs  # easternmost column (just west of 180°)
    assert 0 in xs  # westernmost column (just east of -180°)
    # No spurious mid-ocean columns: only the two seam-adjacent ones
    assert xs == {0, n - 1}


def test_grid_bbox_contains_every_grid_point():
    lat, lon = SEATTLE
    width, height, step = 1000, 600, 20
    min_lon, min_lat, max_lon, max_lat = dm.grid_bbox(lat, lon, width, height, step)
    points = generate_grid_points(
        geopy.Point(lat, lon), int(width / step), int(height / step), step
    )
    for p_lat, p_lon, _, _ in points:
        assert min_lat < p_lat < max_lat
        assert min_lon < p_lon < max_lon


def test_estimate_tile_count_matches_enumeration():
    lat, lon = SEATTLE
    n = dm.estimate_tile_count(lat, lon, 5000, 5000, 20)
    assert n == len(dm.tiles_for_bbox(*dm.grid_bbox(lat, lon, 5000, 5000, 20)))
    # A z14 tile at Seattle is ~1.7km wide: a 5km grid needs a 3x4-ish block,
    # never one tile, never hundreds
    assert 9 <= n <= 25


# ── Synthetic tile encoding (shared by decode + end-to-end tests) ──────────


def encode_tile(features, tile_x, tile_y, zoom=14, extent=4096):
    """
    Build raw MVT bytes for the 'image' layer from records with lon/lat and
    Mapillary-style properties, inverting the decode path's coordinate math.
    """
    encoded_features = []
    for f in features:
        fx, fy = dm.lonlat_to_tile_frac(f["lon"], f["lat"], zoom)
        px = (fx - tile_x) * extent
        py = (1 - (fy - tile_y)) * extent  # y-up, matching decode()'s default
        props = {k: v for k, v in f.items() if k not in ("lon", "lat")}
        encoded_features.append(
            {
                "geometry": {"type": "Point", "coordinates": [px, py]},
                "properties": props,
            }
        )
    return mapbox_vector_tile.encode([{"name": dm.IMAGE_LAYER, "features": encoded_features}])


def make_image(image_id, lon, lat, *, is_pano=True, captured_at=1650000000000, creator_id=42):
    return {
        "id": image_id,
        "lon": lon,
        "lat": lat,
        "is_pano": is_pano,
        "captured_at": captured_at,
        "creator_id": creator_id,
    }


# ── Decoding ───────────────────────────────────────────────────────────────


def test_decode_filters_non_pano():
    lat, lon = SEATTLE
    fx, fy = dm.lonlat_to_tile_frac(lon, lat, 14)
    x, y = int(fx), int(fy)
    tile = encode_tile(
        [
            make_image(1, lon, lat, is_pano=True),
            make_image(2, lon + 1e-4, lat, is_pano=False),  # flat phone photo
        ],
        x,
        y,
    )
    records = dm.decode_image_features(tile, x, y)
    assert [r["id"] for r in records] == ["1"]


def test_decode_coordinates_are_accurate():
    # z14 tile resolution is ~2.4m at the equator (extent 4096); decoded
    # positions must land within a few meters of where they were encoded
    lat, lon = SEATTLE
    fx, fy = dm.lonlat_to_tile_frac(lon, lat, 14)
    x, y = int(fx), int(fy)
    records = dm.decode_image_features(encode_tile([make_image(7, lon, lat)], x, y), x, y)
    assert len(records) == 1
    assert records[0]["lon"] == pytest.approx(lon, abs=5e-5)
    assert records[0]["lat"] == pytest.approx(lat, abs=5e-5)
    assert records[0]["captured_at_ms"] == 1650000000000
    assert records[0]["creator_id"] == 42


def test_decode_empty_or_missing_layer():
    assert (
        dm.decode_image_features(
            mapbox_vector_tile.encode([{"name": "sequence", "features": []}]), 100, 100
        )
        == []
    )


def test_decode_ids_are_strings():
    lat, lon = SEATTLE
    fx, fy = dm.lonlat_to_tile_frac(lon, lat, 14)
    x, y = int(fx), int(fy)
    records = dm.decode_image_features(
        encode_tile([make_image(1234567890123, lon, lat)], x, y), x, y
    )
    assert records[0]["id"] == "1234567890123"


# ── Capture dates ──────────────────────────────────────────────────────────


def test_captured_at_valid_epoch_ms():
    # 2022-01-03T10:43:50Z
    assert dm.captured_at_to_iso_date(1641206630491) == "2022-01-03"


@pytest.mark.parametrize(
    "bogus",
    [
        None,  # missing
        0,  # epoch zero (dead device clock)
        -1000,  # negative
        915148800000,  # 1999 — before street-level imagery existed
        4102444800000,  # year 2100 — future device clock
    ],
)
def test_captured_at_bogus_values_rejected(bogus):
    assert dm.captured_at_to_iso_date(bogus) == ""


# ── Grid assignment ────────────────────────────────────────────────────────


def test_assign_grid_points_map_to_themselves():
    # Consistency between the geodesic grid builder and the equirectangular
    # assignment: every grid point's own coordinates must map back to its
    # own (i, j) index. Odd step counts exercise the asymmetric index range.
    lat, lon = SEATTLE
    step = 20
    for width_steps, height_steps in [(4, 4), (5, 5), (5, 4)]:
        points = generate_grid_points(geopy.Point(lat, lon), width_steps, height_steps, step)
        lats = np.array([p[0] for p in points])
        lons = np.array([p[1] for p in points])
        i, j, in_grid = dm.assign_to_grid(lats, lons, lat, lon, width_steps, height_steps, step)
        assert in_grid.all()
        assert list(zip(i, j, strict=False)) == [(p[2], p[3]) for p in points]


def test_assign_nearest_point_wins():
    lat, lon = SEATTLE
    step = 20
    # ~6m north and ~4m east of the center: rounds to (0, 0)
    img_lat = lat + 6 / dm._M_PER_DEG_LAT
    img_lon = lon + 4 / (dm._M_PER_DEG_LAT * math.cos(math.radians(lat)))
    i, j, in_grid = dm.assign_to_grid(
        np.array([img_lat]), np.array([img_lon]), lat, lon, 4, 4, step
    )
    assert (i[0], j[0]) == (0, 0) and in_grid[0]
    # ~14m north: rounds to (1, 0)
    img_lat = lat + 14 / dm._M_PER_DEG_LAT
    i, j, in_grid = dm.assign_to_grid(np.array([img_lat]), np.array([lon]), lat, lon, 4, 4, step)
    assert (i[0], j[0]) == (1, 0) and in_grid[0]


def test_assign_drops_images_beyond_grid_margin():
    lat, lon = SEATTLE
    step = 20
    # 4x4 steps -> i,j in [-2, 2]. Half a step beyond the edge still rounds
    # to the outermost point; a full step beyond is out of the grid.
    just_inside = lat + (2 * step + 9) / dm._M_PER_DEG_LAT
    well_outside = lat + (3 * step) / dm._M_PER_DEG_LAT
    i, _, in_grid = dm.assign_to_grid(
        np.array([just_inside, well_outside]), np.array([lon, lon]), lat, lon, 4, 4, step
    )
    assert in_grid.tolist() == [True, False]
    assert i[0] == 2


# ── End-to-end download (tiles served from memory) ─────────────────────────


@pytest.fixture
def straddling_city():
    """
    A small city grid deliberately centered on a z14 tile x-boundary so its
    bbox spans two tiles — required to exercise cross-tile dedup.
    """
    lat = SEATTLE[0]
    fx, fy = dm.lonlat_to_tile_frac(SEATTLE[1], lat, 14)
    boundary_lon, _ = dm.tile_frac_to_lonlat(int(fx), fy, 14)
    return lat, boundary_lon


def _run_download(
    monkeypatch, tmp_path, tiles_by_xy, center_lat, center_lon, width=100, height=100, step=20
):
    served = []

    async def fake_fetch(session, url, timeout):
        # The token must travel as an Authorization header, never in the
        # URL (URL-borne credentials leak via exception text into logs).
        m = re.search(r"/2/14/(\d+)/(\d+)$", url)
        assert m, f"unexpected tile URL: {url}"
        assert "access_token" not in url
        assert session.headers.get("Authorization") == "OAuth MLY|test|token"
        xy = (int(m.group(1)), int(m.group(2)))
        served.append(xy)
        return tiles_by_xy.get(xy, mapbox_vector_tile.encode([]))

    monkeypatch.setattr(dm, "_fetch_tile", fake_fetch)
    out_path = str(tmp_path / "test_mapillary_2026-07-05.csv.gz")
    result = asyncio.run(
        dm.download_mapillary_metadata_async(
            "Test City", center_lat, center_lon, width, height, step, "MLY|test|token", out_path
        )
    )
    return result, served


def test_download_end_to_end(monkeypatch, tmp_path, straddling_city):
    lat, lon = straddling_city
    step = 20
    expected_tiles = dm.tiles_for_bbox(*dm.grid_bbox(lat, lon, 100, 100, step))
    assert len(expected_tiles) >= 2  # the straddle worked

    # One pano at the center, one ~20m east (a different grid point), one
    # non-pano to be filtered, one pano with a dead clock (NO_DATE), and the
    # center pano duplicated into every tile (tile-buffer duplication).
    east_lon = lon + 20 / (dm._M_PER_DEG_LAT * math.cos(math.radians(lat)))
    center_pano = make_image(101, lon, lat, captured_at=1641206630491)
    east_pano = make_image(102, east_lon, lat, creator_id=7)
    flat_photo = make_image(103, lon, lat + 1e-5, is_pano=False)
    no_date = make_image(104, lon, lat + 20 / dm._M_PER_DEG_LAT, captured_at=0)

    def features_for(x, y):
        min_lon, min_lat = dm.tile_frac_to_lonlat(x, y + 1, 14)
        max_lon, max_lat = dm.tile_frac_to_lonlat(x + 1, y, 14)
        own = [
            f
            for f in (east_pano, flat_photo, no_date)
            if min_lon <= f["lon"] < max_lon and min_lat <= f["lat"] < max_lat
        ]
        return own + [center_pano]  # duplicated everywhere

    tiles_by_xy = {(x, y): encode_tile(features_for(x, y), x, y) for (x, y) in expected_tiles}
    result, served = _run_download(monkeypatch, tmp_path, tiles_by_xy, lat, lon)
    df = result["df"]

    # Contract: exact 9-column schema, every tile fetched exactly once
    assert list(df.columns) == list(METADATA_DTYPES.keys())
    assert sorted(served) == sorted(expected_tiles)
    assert result["api_requests"] == len(expected_tiles)

    # Cross-tile dedup: pano 101 appears in every tile but only once here
    ok = df[df["status"] == "OK"]
    assert sorted(ok["pano_id"]) == ["101", "102"]
    assert (df["status"] == "NO_DATE").sum() == 1

    # Grid semantics: 100m/20m -> 6x6 grid; every point present exactly once
    # unless covered; total rows = panos + no_date + empty points
    n_points = 6 * 6
    covered = df[df["status"] != "ZERO_RESULTS"][["query_lat", "query_lon"]]
    n_covered_points = len(covered.drop_duplicates())
    assert (df["status"] == "ZERO_RESULTS").sum() == n_points - n_covered_points
    assert len(df) == 2 + 1 + (n_points - n_covered_points)

    # Panos landed on distinct nearest grid points
    assert len(ok[["query_lat", "query_lon"]].drop_duplicates()) == 2

    # Field contents
    center_row = ok[ok["pano_id"] == "101"].iloc[0]
    # the shared loader parses capture_date to Timestamp, as for GSV runs
    assert center_row["capture_date"] == pd.Timestamp("2022-01-03")
    assert center_row["copyright_info"] == "© Mapillary contributor 42"
    assert center_row["pano_lat"] == pytest.approx(lat, abs=5e-5)
    assert center_row["pano_lon"] == pytest.approx(lon, abs=5e-5)
    east_row = ok[ok["pano_id"] == "102"].iloc[0]
    assert east_row["copyright_info"] == "© Mapillary contributor 7"

    # File on disk parses through the shared loader path (result already did,
    # but verify the write is a real gzip csv)
    with gzip.open(result["filename_with_path"], "rt") as f:
        assert f.readline().strip() == ",".join(METADATA_DTYPES.keys())

    # Timestamps are ISO UTC and ordered
    started = datetime.fromisoformat(result["started_at"])
    finished = datetime.fromisoformat(result["finished_at"])
    assert started.tzinfo == UTC and started <= finished


def test_download_city_with_no_imagery(monkeypatch, tmp_path):
    # Every tile empty: pure ZERO_RESULTS fill, one row per grid point
    lat, lon = SEATTLE
    result, _ = _run_download(monkeypatch, tmp_path, {}, lat, lon)
    df = result["df"]
    assert (df["status"] == "ZERO_RESULTS").all()
    assert len(df) == 6 * 6
    assert df["pano_id"].isna().all()


def test_download_rejects_non_csv_gz_path(tmp_path):
    with pytest.raises(ValueError, match="csv.gz"):
        asyncio.run(
            dm.download_mapillary_metadata_async(
                "X", *SEATTLE, 100, 100, 20, "tok", str(tmp_path / "out.csv")
            )
        )


def test_run_stats_for_mapillary_have_no_google_count():
    # calculate_run_stats feeds db.register_run: for mapillary runs the
    # Google-copyright breakdown must be NULL, not zero-by-accident
    from datetime import date

    from streetscape_metadata_tracker.analysis import calculate_run_stats
    from tests.conftest import make_city_df, make_mapillary_city_df

    m_df = make_mapillary_city_df(
        [("m1", "2021-03-01"), ("m2", "2022-03-01"), ("m3", "2023-03-01")], panos_per_point=3
    )
    stats = calculate_run_stats(m_df, date(2026, 1, 15), provider="mapillary")
    assert stats["unique_panos"] == 3
    assert stats["unique_google_panos"] is None
    assert stats["status_ok"] == 3 and stats["status_zero_results"] == 1

    g_df = make_city_df([("p1", "2021-03-01")])
    g_stats = calculate_run_stats(g_df, date(2026, 1, 15))
    assert g_stats["unique_google_panos"] == 1  # gsv path unchanged


def test_download_pano_outside_grid_is_dropped(monkeypatch, tmp_path):
    # A pano inside the fetched tiles but beyond the grid margin must not
    # produce a row (the tile covers far more area than a small grid)
    lat, lon = SEATTLE
    far_lon = lon + 500 / (dm._M_PER_DEG_LAT * math.cos(math.radians(lat)))
    fx, fy = dm.lonlat_to_tile_frac(far_lon, lat, 14)
    x, y = int(fx), int(fy)
    tiles = {(x, y): encode_tile([make_image(201, far_lon, lat)], x, y)}
    result, _ = _run_download(monkeypatch, tmp_path, tiles, lat, lon)
    assert (result["df"]["status"] == "ZERO_RESULTS").all()


# ── Latitude-local grid assignment accuracy (audit 2026-07-11, M2) ──────────


def test_assign_to_grid_matches_geodesic_grid_far_from_center_at_equator():
    """A pano EXACTLY at grid point (i=120, j=0) — placed with the same
    geodesic math that builds the grid — must assign to i=120. The old
    global-mean 111,320 m/° overstated equatorial dy by ~0.67% (true
    ≈110,574 m/°), i.e. +0.8 rows at 2.4 km from center → i=121."""
    origin = geopy.Point(0.0, 30.0)
    north = geopy.distance.distance(meters=120 * 20).destination(origin, 0)
    i, j, in_grid = dm.assign_to_grid(
        np.array([north.latitude]),
        np.array([north.longitude]),
        0.0,
        30.0,
        width_steps=250,
        height_steps=250,
        step_length=20,
    )
    assert (int(i[0]), int(j[0])) == (120, 0)
    assert bool(in_grid[0])


def test_assign_to_grid_matches_geodesic_grid_far_corner_mid_latitude():
    """Same check at Seattle's latitude on a far corner point (i=120, j=120),
    exercising both the dy series and the per-row cos-latitude dx scale."""
    lat0, lon0 = 47.6, -122.3
    north = geopy.distance.distance(meters=120 * 20).destination(geopy.Point(lat0, lon0), 0)
    corner = geopy.distance.distance(meters=120 * 20).destination(north, 90)
    i, j, in_grid = dm.assign_to_grid(
        np.array([corner.latitude]),
        np.array([corner.longitude]),
        lat0,
        lon0,
        width_steps=250,
        height_steps=250,
        step_length=20,
    )
    assert (int(i[0]), int(j[0])) == (120, 120)
    assert bool(in_grid[0])

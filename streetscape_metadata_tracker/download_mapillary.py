"""
Mapillary metadata downloader (issue #89).

Unlike Google Street View — which only answers "what's the nearest pano to
point X?", forcing one API request per grid point — Mapillary publishes its
image metadata as z14 vector tiles: one request returns every image in a
~2.4 km (at the equator) map-tile square as compact protobuf, including the
image id, capture timestamp, position, and an is_pano flag. A whole city is
typically a few dozen tile requests.

Collection model (decided in issue #89):
- Only 360-degree panoramas are kept (is_pano true); flat phone photos are
  dropped at ingest.
- ALL panos are kept — one CSV row per image, with query_lat/query_lon set
  to the image's nearest point on the city's frozen sampling grid. Grid
  points with no pano get a single ZERO_RESULTS row. Coverage rate (% of
  grid points with >= 1 pano) is therefore directly comparable to GSV,
  while raw pano counts are a census here vs a grid sample for GSV.

The output CSV uses the exact same 9-column schema as the GSV downloader
(config.METADATA_DTYPES), so analysis, diffing, and the frontend consume
both providers' files identically.

No resume logic: a full city is seconds of tile fetches (vs hours of
per-point requests for GSV), so an interrupted run just restarts.
"""

import asyncio
import gzip
import logging
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import backoff
import geopy.distance
import mapbox_vector_tile
import numpy as np
import pandas as pd
from tqdm import tqdm

from .config import METADATA_DTYPES
from .download_common import DownloadError, generate_grid_points, redact_credentials
from .fileutils import load_city_csv_file

logger = logging.getLogger(__name__)

TILE_ZOOM = 14  # the only zoom level whose tiles carry per-image metadata
# The access token is sent as an `Authorization: OAuth <token>` header, NOT
# a query parameter: HTTP-client exceptions stringify with the full request
# URL, so a URL-borne token would leak into logs (and from log tails into
# the scheduler's alert emails).
TILE_URL_TEMPLATE = "https://tiles.mapillary.com/maps/vtp/mly1_computed_public/2/{z}/{x}/{y}"
IMAGE_LAYER = "image"

# Meters per degree of latitude (WGS84 mean). Kept for rough offset math in
# tests/estimates; the actual grid assignment uses the latitude-local series
# below (the mean constant mis-assigned edge panos by whole grid rows —
# ~0.7% error at the equator is +1 row at 2.5 km from center).
_M_PER_DEG_LAT = 111320.0


def _meters_per_degree(lat_deg):
    """
    (m_per_deg_lat, m_per_deg_lon) at a latitude, via the standard WGS84
    series expansion. Accepts scalars or numpy arrays. Matches the geodesic
    math that builds the grid to well under a meter over a city-sized area,
    so nearest-grid-point assignment can't drift by rows near the edges.
    """
    phi = np.radians(lat_deg)
    m_lat = (
        111132.92 - 559.82 * np.cos(2 * phi) + 1.175 * np.cos(4 * phi) - 0.0023 * np.cos(6 * phi)
    )
    m_lon = 111412.84 * np.cos(phi) - 93.5 * np.cos(3 * phi) + 0.118 * np.cos(5 * phi)
    return m_lat, m_lon


# ── Slippy-map tile math (stdlib only) ─────────────────────────────────────


def lonlat_to_tile_frac(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Fractional Web-Mercator tile coordinates (x, y; y from the top)."""
    n = 2**zoom
    fx = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    fy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return fx, fy


def tile_frac_to_lonlat(fx: float, fy: float, zoom: int) -> tuple[float, float]:
    """Inverse of lonlat_to_tile_frac."""
    n = 2**zoom
    lon = fx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * fy / n))))
    return lon, lat


def tiles_for_bbox(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float, zoom: int = TILE_ZOOM
) -> list[tuple[int, int]]:
    """
    All (x, y) tile indices at the given zoom intersecting the bbox.

    A bbox that crosses the antimeridian (min_lon > max_lon after geopy
    normalizes longitudes to ±180 — e.g. Suva, Fiji) wraps: it covers the
    x columns from min_lon to the right edge plus those from the left edge
    to max_lon. The naive single range was empty there, silently yielding
    a 0-tile (0-pano) run.
    """
    fx_min, fy_max = lonlat_to_tile_frac(min_lon, min_lat, zoom)  # y grows southward
    fx_max, fy_min = lonlat_to_tile_frac(max_lon, max_lat, zoom)
    n = 2**zoom
    if fx_min > fx_max:  # bbox crosses the antimeridian
        x_indices = [*range(max(0, int(fx_min)), n), *range(0, min(n - 1, int(fx_max)) + 1)]
    else:
        x_indices = list(range(max(0, int(fx_min)), min(n - 1, int(fx_max)) + 1))
    y_range = range(max(0, int(fy_min)), min(n - 1, int(fy_max)) + 1)
    return [(x, y) for x in x_indices for y in y_range]


def grid_bbox(
    center_lat: float, center_lon: float, grid_width: float, grid_height: float, step_length: float
) -> tuple[float, float, float, float]:
    """
    (min_lon, min_lat, max_lon, max_lat) covering the sampling grid plus a
    half-step margin, computed with the same geodesic math that builds the
    grid so the two always agree. The margin admits images that lie just
    outside the outermost grid points but are still nearest to them.
    """
    origin = geopy.Point(center_lat, center_lon)
    half_h = grid_height / 2 + step_length / 2
    half_w = grid_width / 2 + step_length / 2
    north = geopy.distance.distance(meters=half_h).destination(origin, 0)
    south = geopy.distance.distance(meters=half_h).destination(origin, 180)
    east = geopy.distance.distance(meters=half_w).destination(origin, 90)
    west = geopy.distance.distance(meters=half_w).destination(origin, 270)
    return west.longitude, south.latitude, east.longitude, north.latitude


def estimate_tile_count(
    center_lat: float,
    center_lon: float,
    grid_width: float,
    grid_height: float,
    step_length: float = 20,
) -> int:
    """
    Number of z14 tile requests a run will make — the Mapillary analogue of
    the scheduler's grid-point request estimate for GSV.
    """
    return len(
        tiles_for_bbox(*grid_bbox(center_lat, center_lon, grid_width, grid_height, step_length))
    )


# ── Tile decoding ──────────────────────────────────────────────────────────


def decode_image_features(
    tile_bytes: bytes, tile_x: int, tile_y: int, zoom: int = TILE_ZOOM
) -> list[dict[str, Any]]:
    """
    Extract pano image records from one raw vector tile.

    Returns dicts with: id (str), lon, lat, captured_at_ms (int or None),
    creator_id. Non-pano images are dropped here (issue #89 scope: only
    360-degree imagery of GSV-comparable quality).
    """
    decoded = mapbox_vector_tile.decode(tile_bytes)
    layer = decoded.get(IMAGE_LAYER)
    if not layer:
        return []
    extent = layer.get("extent", 4096)

    records = []
    for feature in layer["features"]:
        props = feature.get("properties", {})
        if not props.get("is_pano"):
            continue
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "Point":
            continue
        px, py = geometry["coordinates"]
        # decode() returns y-up tile-local coords; convert to global fractions
        fx = tile_x + px / extent
        fy = tile_y + (1 - py / extent)
        lon, lat = tile_frac_to_lonlat(fx, fy, zoom)

        image_id = props.get("id", feature.get("id"))
        if image_id is None:
            continue
        captured_at = props.get("captured_at")
        records.append(
            {
                "id": str(image_id),
                "lon": lon,
                "lat": lat,
                "captured_at_ms": captured_at,
                "creator_id": props.get("creator_id"),
            }
        )
    return records


def captured_at_to_iso_date(captured_at_ms) -> str:
    """
    Unix epoch milliseconds -> 'YYYY-MM-DD' (UTC), or '' when missing or
    implausible. Mapillary timestamps come from contributor device clocks,
    so guard against epoch-zero and other bogus values (anything before
    Mapillary could plausibly have imagery, or in the future).
    """
    if not captured_at_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(int(captured_at_ms) / 1000, tz=UTC)
    except (ValueError, OSError, OverflowError):
        return ""
    if dt.year < 2004 or dt > datetime.now(UTC):
        return ""
    return dt.date().isoformat()


# ── Grid assignment ────────────────────────────────────────────────────────


def assign_to_grid(
    image_lats: np.ndarray,
    image_lons: np.ndarray,
    center_lat: float,
    center_lon: float,
    width_steps: int,
    height_steps: int,
    step_length: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Vectorized nearest-grid-point assignment.

    The grid is a regular lattice of step_length meters indexed by
    (i, j) = (north, east) offsets from the center (see
    generate_grid_points), so the nearest point is just a rounded division
    in a local equirectangular projection — no spatial index needed.

    Returns (i, j, in_grid) arrays; in_grid is False for images farther
    than half a step beyond the outermost grid points, which the caller
    drops.
    """
    # Latitude-local scales: the grid is built geodesically, so a global
    # mean m/° mis-assigns by whole rows near the grid edges. dy uses the
    # series at the center↔image midpoint latitude; dx uses each image's
    # own latitude (grid rows are constant-latitude, and their east-west
    # spacing shrinks with cos φ at THAT row, not at the center).
    m_lat_mid, _ = _meters_per_degree((image_lats + center_lat) / 2)
    _, m_lon_local = _meters_per_degree(image_lats)
    dy_m = (image_lats - center_lat) * m_lat_mid
    dx_m = (image_lons - center_lon) * m_lon_local
    i = np.rint(dy_m / step_length).astype(int)
    j = np.rint(dx_m / step_length).astype(int)

    # Replicate generate_grid_points' index ranges exactly (note: Python
    # floor division makes the ranges asymmetric for odd step counts).
    i_min, i_max = -height_steps // 2, height_steps // 2
    j_min, j_max = -width_steps // 2, width_steps // 2
    in_grid = (i >= i_min) & (i <= i_max) & (j >= j_min) & (j <= j_max)
    return i, j, in_grid


# ── Download ───────────────────────────────────────────────────────────────


@backoff.on_exception(
    backoff.expo, (asyncio.TimeoutError, aiohttp.ClientError), max_tries=3, max_time=60
)
async def _fetch_tile(
    session: aiohttp.ClientSession, url: str, timeout: aiohttp.ClientTimeout
) -> bytes:
    async with session.get(url, timeout=timeout) as response:
        if response.status in (401, 403):
            raise DownloadError(
                f"Mapillary rejected the access token (HTTP {response.status}). "
                "Check MAPILLARY_ACCESS_TOKEN."
            )
        if response.status != 200:
            # 429/5xx raise ClientResponseError, which backoff retries
            response.raise_for_status()
        return await response.read()


async def download_mapillary_metadata_async(
    city_name: str,
    center_lat: float,
    center_lon: float,
    grid_width: float,
    grid_height: float,
    step_length: float,
    access_token: str,
    output_csv_gz_path: str,
    connection_limit: int = 5,
    request_timeout: float = 30,
) -> dict[str, Any]:
    """
    Fetch Mapillary pano metadata for a city and write it as a run csv.gz.

    Same calling convention as download_gsv_metadata_async: the caller
    decides the output filename (skip policy and dated naming live in the
    CLI/scheduler layer, not here).

    Returns:
        Dict with:
            df: DataFrame containing the metadata (METADATA_DTYPES schema)
            filename_with_path: the written .csv.gz path
            api_requests: number of tile requests issued this call
            started_at / finished_at: UTC ISO 8601 timestamps
    """
    started_at = datetime.now(UTC).isoformat()
    query_timestamp = started_at

    if not output_csv_gz_path.endswith(".csv.gz"):
        raise ValueError(f"output_csv_gz_path must end in .csv.gz, got: {output_csv_gz_path}")
    Path(os.path.dirname(os.path.abspath(output_csv_gz_path))).mkdir(parents=True, exist_ok=True)

    width_steps = int(grid_width / step_length)
    height_steps = int(grid_height / step_length)
    origin = geopy.Point(center_lat, center_lon)
    grid_points = generate_grid_points(origin, width_steps, height_steps, step_length)
    point_by_index = {(i, j): (lat, lon) for lat, lon, i, j in grid_points}

    bbox = grid_bbox(center_lat, center_lon, grid_width, grid_height, step_length)
    tiles = tiles_for_bbox(*bbox)
    logger.info(
        f"Fetching Mapillary metadata for {city_name}: {len(tiles)} z{TILE_ZOOM} "
        f"tiles covering bbox {tuple(round(v, 4) for v in bbox)}"
    )

    api_requests = 0
    timeout = aiohttp.ClientTimeout(total=request_timeout)
    semaphore = asyncio.Semaphore(connection_limit)
    progress_bar = tqdm(total=len(tiles), desc=f"Downloading Mapillary tiles for {city_name}")

    async def fetch_one(x: int, y: int) -> list[dict[str, Any]]:
        nonlocal api_requests
        url = TILE_URL_TEMPLATE.format(z=TILE_ZOOM, x=x, y=y)
        async with semaphore:
            api_requests += 1
            tile_bytes = await _fetch_tile(session, url, timeout)
        progress_bar.update(1)
        return decode_image_features(tile_bytes, x, y)

    try:
        # Token in a header, not the URL — see TILE_URL_TEMPLATE comment.
        async with aiohttp.ClientSession(
            headers={"Authorization": f"OAuth {access_token}"}
        ) as session:
            results = await asyncio.gather(*(fetch_one(x, y) for x, y in tiles))
    except DownloadError as e:
        # e.g. the rejected-token error from _fetch_tile; attach the spent
        # request count so the caller can still record it in the ledger.
        e.api_requests = api_requests
        raise
    except (TimeoutError, aiohttp.ClientError) as e:
        error = DownloadError(f"Mapillary tile download failed: {redact_credentials(e)}")
        error.api_requests = api_requests
        raise error from e
    finally:
        progress_bar.close()

    # Tiles are encoded with a buffer, so features near tile edges appear in
    # two tiles — dedup on image id.
    images_by_id = {}
    for records in results:
        for record in records:
            images_by_id[record["id"]] = record
    images = list(images_by_id.values())
    logger.info(
        f"Decoded {sum(len(r) for r in results)} pano features "
        f"({len(images)} unique) from {len(tiles)} tiles"
    )

    rows = []
    covered_points = set()
    if images:
        lats = np.array([img["lat"] for img in images])
        lons = np.array([img["lon"] for img in images])
        i_idx, j_idx, in_grid = assign_to_grid(
            lats, lons, center_lat, center_lon, width_steps, height_steps, step_length
        )
        for img, i, j, keep in zip(images, i_idx, j_idx, in_grid, strict=False):
            if not keep:
                continue
            grid_lat, grid_lon = point_by_index[(int(i), int(j))]
            capture_date = captured_at_to_iso_date(img["captured_at_ms"])
            creator = img["creator_id"]
            copyright_info = (
                f"© Mapillary contributor {creator}" if creator is not None else "© Mapillary"
            )
            rows.append(
                {
                    "query_lat": grid_lat,
                    "query_lon": grid_lon,
                    "query_timestamp": query_timestamp,
                    "pano_lat": img["lat"],
                    "pano_lon": img["lon"],
                    "pano_id": img["id"],
                    "capture_date": capture_date,
                    "copyright_info": copyright_info,
                    # Mirror GSV's convention: an image without a usable
                    # capture date is present but doesn't count as coverage
                    "status": "OK" if capture_date else "NO_DATE",
                }
            )
            covered_points.add((int(i), int(j)))

    for (i, j), (grid_lat, grid_lon) in point_by_index.items():
        if (i, j) not in covered_points:
            rows.append(
                {
                    "query_lat": grid_lat,
                    "query_lon": grid_lon,
                    "query_timestamp": query_timestamp,
                    "pano_lat": None,
                    "pano_lon": None,
                    "pano_id": None,
                    "capture_date": None,
                    "copyright_info": None,
                    "status": "ZERO_RESULTS",
                }
            )

    df = pd.DataFrame(rows, columns=list(METADATA_DTYPES.keys()))
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    with gzip.open(output_csv_gz_path, "wb") as f:
        f.write(csv_bytes)

    # Read back through the shared loader so dtypes match GSV runs exactly
    df = load_city_csv_file(output_csv_gz_path)
    n_panos = int((df["status"] == "OK").sum())
    logger.info(
        f"Wrote {len(df)} rows ({n_panos} panos, "
        f"{len(point_by_index) - len(covered_points)} empty grid points) "
        f"to {output_csv_gz_path}"
    )

    return {
        "df": df,
        "filename_with_path": output_csv_gz_path,
        "api_requests": api_requests,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
    }

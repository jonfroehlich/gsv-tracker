"""
Core street-coverage analysis (no network access).

Given a run's pano DataFrame and an OSM street-edge GeoDataFrame, decide which
street segments have imagery coverage and summarize by `highway` type. The
network fetch lives in `download_street_network`; everything here operates on
already-loaded geometries so it is fully unit-testable without hitting Overpass.

Coverage definition (issue #24, intentionally liberal): a street segment is
"covered" if at least one pano lies within `match_dist_m` metres of it. GSV is a
grid *sample* (one pano per sampled grid point) while Mapillary is a *census*;
the metre threshold — roughly one grid step — lets a street sampled between grid
points still count as covered. This over-counts rather than under-counts, which
matches the issue's ask ("something rather liberal").
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import pandas as pd

from streetscape_metadata_tracker.analysis import is_google_copyright

logger = logging.getLogger(__name__)

WGS84 = "EPSG:4326"
DEFAULT_MATCH_DIST_M = 25.0
_YEAR_SECONDS = 365.25 * 24 * 3600

# OSM `highway` values collapsed into a small, ordered set of buckets for the
# by-type breakdown. Anything unrecognized falls through to "other".
_HIGHWAY_BUCKETS = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "unclassified",
    "service",
    "living_street",
]


def normalize_highway(highway: Any) -> str:
    """
    Collapse an OSM `highway` tag to a canonical bucket.

    OSM (and osmnx after simplification) may give a single string or a list of
    strings when a simplified edge merged ways of different classes; we take the
    first recognized bucket, dropping the common ``_link`` suffix so e.g.
    ``motorway_link`` counts as ``motorway``.
    """
    values = highway if isinstance(highway, (list, tuple)) else [highway]
    for value in values:
        if value is None:
            continue
        tag = str(value).strip().lower()
        if tag.endswith("_link"):
            tag = tag[: -len("_link")]
        if tag in _HIGHWAY_BUCKETS:
            return tag
    return "other"


def select_pano_points(df: pd.DataFrame, provider: str) -> gpd.GeoDataFrame:
    """
    Extract located panos from a run DataFrame as a WGS84 point GeoDataFrame.

    Keeps only ``status == 'OK'`` rows with non-null pano coordinates. For GSV,
    restricts to official Google imagery (exact ``© Google`` match, mirroring the
    stats/JSON/frontend definition); for other providers keeps every pano.
    Retains ``capture_date`` (coerced to datetime) so coverage can be aged.
    """
    mask = (df["status"] == "OK") & df["pano_lat"].notna() & df["pano_lon"].notna()
    if provider == "gsv":
        mask = mask & is_google_copyright(df["copyright_info"])

    panos = df.loc[mask, ["pano_lat", "pano_lon", "capture_date"]].copy()
    if not pd.api.types.is_datetime64_any_dtype(panos["capture_date"]):
        panos["capture_date"] = pd.to_datetime(panos["capture_date"], errors="coerce")

    geometry = gpd.points_from_xy(panos["pano_lon"], panos["pano_lat"])
    return gpd.GeoDataFrame(
        panos[["capture_date"]].reset_index(drop=True),
        geometry=geometry,
        crs=WGS84,
    )


def _age_years(capture_date: pd.Timestamp | None, run_ts: pd.Timestamp) -> float | None:
    """Pano age in years relative to the run date, or None if the date is unknown."""
    if capture_date is None or pd.isna(capture_date):
        return None
    return (run_ts - capture_date).total_seconds() / _YEAR_SECONDS


def compute_street_coverage(
    edges: gpd.GeoDataFrame,
    panos: gpd.GeoDataFrame,
    run_date: str,
    match_dist_m: float = DEFAULT_MATCH_DIST_M,
) -> gpd.GeoDataFrame:
    """
    Tag each street edge with coverage against the given panos.

    Args:
        edges: WGS84 LineString GeoDataFrame with a ``highway`` column (from
            osmnx ``graph_to_gdfs``); a ``length`` column (metres) is used if
            present, otherwise segment length is measured in a local UTM CRS.
        panos: WGS84 point GeoDataFrame from `select_pano_points`, carrying
            ``capture_date``.
        run_date: ``YYYY-MM-DD``; ages are pinned to it (deterministic).
        match_dist_m: coverage threshold in metres.

    Returns:
        A copy of ``edges`` (WGS84, RangeIndex) with added columns:
        ``highway_bucket``, ``length_m``, ``covered`` (bool),
        ``nearest_pano_date`` (str|None), ``nearest_pano_age_years`` (float|None).
    """
    run_ts = pd.Timestamp(run_date)
    out = edges.reset_index(drop=True).copy()
    out["highway_bucket"] = out["highway"].apply(normalize_highway)

    # Work in a local metric CRS so distances and lengths are in metres. All
    # cities here are far smaller than a UTM zone, so a single estimated zone is
    # accurate to well under the match threshold.
    metric_crs = out.estimate_utm_crs()
    edges_m = out.to_crs(metric_crs)

    if "length" in out.columns:
        out["length_m"] = pd.to_numeric(out["length"], errors="coerce").fillna(edges_m.length)
    else:
        out["length_m"] = edges_m.length

    out["covered"] = False
    out["nearest_pano_date"] = None
    out["nearest_pano_age_years"] = None

    if len(panos) > 0:
        panos_m = panos.to_crs(metric_crs)
        # Nearest pano per edge within the threshold. sjoin_nearest keeps only
        # edges with a match, and can emit ties (>1 pano at equal distance) as
        # duplicate rows — collapse to the closest, breaking ties by newest date.
        joined = gpd.sjoin_nearest(
            edges_m, panos_m, how="inner", max_distance=match_dist_m, distance_col="_dist"
        )
        if len(joined) > 0:
            joined = joined.sort_values(["_dist", "capture_date"], ascending=[True, False])
            nearest = joined[~joined.index.duplicated(keep="first")]
            out.loc[nearest.index, "covered"] = True
            for edge_idx, cap_date in nearest["capture_date"].items():
                if pd.notna(cap_date):
                    out.at[edge_idx, "nearest_pano_date"] = cap_date.date().isoformat()
                    out.at[edge_idx, "nearest_pano_age_years"] = round(
                        _age_years(cap_date, run_ts), 3
                    )

    return out


def _bucket_order(bucket: str) -> int:
    try:
        return _HIGHWAY_BUCKETS.index(bucket)
    except ValueError:
        return len(_HIGHWAY_BUCKETS)  # "other" sorts last


def summarize_coverage(covered_edges: gpd.GeoDataFrame) -> dict[str, Any]:
    """
    Aggregate per-segment coverage into by-highway-type and overall stats.

    Reports coverage two ways — by segment count and by street length — because a
    city can have most *segments* covered yet a large fraction of *kilometres*
    uncovered (long rural roads), and vice versa.
    """

    def _block(group: pd.DataFrame) -> dict[str, Any]:
        segments = int(len(group))
        covered = group["covered"]
        num_covered = int(covered.sum())
        length_km = float(group["length_m"].sum()) / 1000.0
        length_km_covered = float(group.loc[covered, "length_m"].sum()) / 1000.0
        ages = pd.to_numeric(group.loc[covered, "nearest_pano_age_years"], errors="coerce").dropna()
        return {
            "segments": segments,
            "covered": num_covered,
            "length_km": round(length_km, 3),
            "length_km_covered": round(length_km_covered, 3),
            "coverage_pct_by_count": round(100.0 * num_covered / segments, 1) if segments else 0.0,
            "coverage_pct_by_length": round(100.0 * length_km_covered / length_km, 1)
            if length_km
            else 0.0,
            "median_covered_age_years": round(float(ages.median()), 2) if len(ages) else None,
        }

    by_type = {bucket: _block(group) for bucket, group in covered_edges.groupby("highway_bucket")}
    by_type = dict(sorted(by_type.items(), key=lambda kv: _bucket_order(kv[0])))

    totals = _block(covered_edges)
    totals["uncovered"] = totals["segments"] - totals["covered"]
    totals["uncovered_pct_by_count"] = round(100.0 - totals["coverage_pct_by_count"], 1)
    totals["uncovered_pct_by_length"] = round(100.0 - totals["coverage_pct_by_length"], 1)

    return {"coverage_by_highway": by_type, "totals": totals}


def build_streets_geojson(
    covered_edges: gpd.GeoDataFrame,
    *,
    city_id: str,
    provider: str,
    run_date: str,
    match_dist_m: float,
    source_csv: str,
) -> dict[str, Any]:
    """
    Assemble the published GeoJSON FeatureCollection.

    Each feature is a street segment with coverage properties; the collection's
    top-level ``properties.metadata`` carries the by-type/overall summary so the
    frontend can draw both the map layer and the breakdown chart from one file.
    """
    summary = summarize_coverage(covered_edges)

    features: list[dict[str, Any]] = []
    for row in covered_edges.itertuples(index=False):
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geom.__geo_interface__,
                "properties": {
                    "highway": row.highway_bucket,
                    "length_m": round(float(row.length_m), 1),
                    "covered": bool(row.covered),
                    "nearest_pano_date": row.nearest_pano_date,
                    "nearest_pano_age_years": row.nearest_pano_age_years,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "properties": {
            "metadata": {
                "schema_version": 1,
                "kind": "street_coverage",
                "city_id": city_id,
                "provider": provider,
                "run_date": run_date,
                "match_dist_m": match_dist_m,
                "source_csv": source_csv,
                **summary,
            }
        },
        "features": features,
    }

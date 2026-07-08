"""
Fetch the OSM drivable street network for a city (issue #24).

Unlike the exploratory starter this replaces, the network is fetched for the
city's **frozen grid bounding box** (never re-geocoded), so the streets line up
exactly with the sampled grid the pano runs use. The raw graph is frozen to an
unpublished GraphML cache under ``data/osm_cache/`` — streets change slowly, so
we fetch once per city and reuse until ``--refresh``. GraphML (not GeoJSON) is
used for the cache because it round-trips osmnx's list-valued tags and is skipped
by the publish glob (which only ships ``*.csv.gz`` / ``*.json.gz``).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import geopandas as gpd
import networkx as nx
import osmnx as ox
from tenacity import retry, stop_after_attempt, wait_exponential

from gsv_metadata_tracker.db import CityRow
from gsv_metadata_tracker.download_mapillary import grid_bbox

logger = logging.getLogger(__name__)

# Quiet by default; the CLI configures the root logger. use_cache also stores
# Overpass responses so re-fetches during development are cheap.
ox.settings.log_console = False
ox.settings.use_cache = True
ox.settings.timeout = 60

NETWORK_TYPE = "drive"


def _cache_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "osm_cache")


def network_cache_path(city_id: str, data_dir: str) -> str:
    """Unpublished GraphML path for a city's frozen street network."""
    return os.path.join(_cache_dir(data_dir), f"{city_id}_streets_network.graphml")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def _download_graph(bbox, network_type: str) -> nx.MultiDiGraph:
    """Download a simplified drive network for the bbox, retrying on failure."""
    # osmnx 2.x expects bbox=(left, bottom, right, top) == (min_lon, min_lat,
    # max_lon, max_lat), exactly what grid_bbox returns.
    return ox.graph_from_bbox(
        bbox=bbox,
        network_type=network_type,
        simplify=True,
        retain_all=True,
        truncate_by_edge=True,
    )


def fetch_graph(
    city_row: CityRow,
    data_dir: str,
    *,
    refresh: bool = False,
    network_type: str = NETWORK_TYPE,
) -> nx.MultiDiGraph:
    """
    Return the city's street graph, from the frozen cache or Overpass.

    The bbox comes from the frozen grid geometry via `grid_bbox`, so the network
    matches the sampled area. When a cache exists and ``refresh`` is False it is
    loaded; otherwise the graph is downloaded and cached.
    """
    # Keep osmnx's raw HTTP response cache inside the (unpublished) osm_cache
    # dir rather than a stray ./cache in the cwd.
    ox.settings.cache_folder = os.path.join(_cache_dir(data_dir), "osmnx")

    cache_path = network_cache_path(city_row.city_id, data_dir)
    if not refresh and os.path.exists(cache_path):
        logger.info("Loading frozen street network from %s", cache_path)
        return ox.load_graphml(cache_path)

    bbox = grid_bbox(
        city_row.center_lat,
        city_row.center_lon,
        city_row.grid_width_m,
        city_row.grid_height_m,
        city_row.step_m,
    )
    logger.info(
        "Downloading OSM %s network for %s within frozen bbox %s",
        network_type,
        city_row.city_id,
        bbox,
    )
    graph = _download_graph(bbox, network_type)
    logger.info(
        "Downloaded %d nodes / %d edges", graph.number_of_nodes(), graph.number_of_edges()
    )

    os.makedirs(_cache_dir(data_dir), exist_ok=True)
    ox.save_graphml(graph, cache_path)
    logger.info("Froze street network to %s", cache_path)
    return graph


def graph_to_edges(graph: nx.MultiDiGraph) -> gpd.GeoDataFrame:
    """
    Flatten a street graph to a WGS84 edge GeoDataFrame for coverage matching.

    Keeps one row per undirected edge (osmnx returns both directions of a
    two-way street; they share geometry, so we drop duplicates) with ``highway``,
    ``length`` (metres), and LineString ``geometry``.
    """
    edges = ox.graph_to_gdfs(graph, nodes=False)
    keep = [c for c in ("highway", "length", "geometry") if c in edges.columns]
    edges = edges[keep].reset_index(drop=True)

    # Collapse reciprocal directed edges (identical geometry) to avoid
    # double-counting segments in the coverage stats.
    edges = edges.loc[~edges.geometry.apply(lambda g: g.wkb).duplicated()].reset_index(
        drop=True
    )
    return edges


def fetch_street_edges(
    city_row: CityRow,
    data_dir: str,
    *,
    refresh: bool = False,
    network_type: str = NETWORK_TYPE,
) -> gpd.GeoDataFrame:
    """Convenience wrapper: fetch the graph and return its edge GeoDataFrame."""
    graph = fetch_graph(
        city_row, data_dir, refresh=refresh, network_type=network_type
    )
    return graph_to_edges(graph)

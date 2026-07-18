"""
streetscape_street_analyzer — OSM street-coverage analysis (issues #24/#103).

A standalone enrichment layer, separate from the main run pipeline: given an
existing run's pano CSV and a city's frozen grid geometry, it overlays the
frozen OpenStreetMap drivable street network (a provider-agnostic catalog
asset, issue #103) and decides, per street segment, whether it has at least
one nearby pano (a deliberately liberal definition — see
`street_coverage.compute_street_coverage`). Results are broken down by OSM
`highway` type and written as a published GeoJSON artifact for the web
frontend.

A second, active collection modality also lives here (issue #99): the road-walk
collector (`collect`) walks each frozen OSM edge, samples on-street points every
~15 m along the centerline, and queries GSV for the nearest pano at each — so
street association is by construction and coverage is FRACTIONAL per edge rather
than the boolean the grid-attribution `analyze` path produces. It reuses the
grid downloader's hardened request engine (`download_gsv.collect_points_async`:
rate limiter + OVER_QUERY_LIMIT retry + failed-point guard) but on its own
isolated key/budget channel (`GMAPS_STREETS_API_KEY` / the `gsv_streets`
`api_usage` ledger), and writes a dated `..._streetwalk_sp{N}_{DATE}.csv.gz`
snapshot plus a per-edge `..._coverage.json.gz`, cataloged in `street_walks`.

Kept as its own top-level package so the heavy geospatial stack (osmnx,
geopandas, shapely) never enters the core pipeline's import graph, and as the
clean extraction seam should street work ever be split out (issue #99's
packaging decision). Catalog access is read-only for the core tables
(cities/runs); the package writes only its own `street_networks` / `street_walks`
rows.

Run it as a module:

    python -m streetscape_street_analyzer.analyze "Seattle, WA"   # grid attribution
    python -m streetscape_street_analyzer.collect "Seattle, WA"   # road-walk collection
"""

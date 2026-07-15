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

Kept as its own top-level package so the heavy geospatial stack (osmnx,
geopandas, shapely) never enters the core pipeline's import graph, and as the
clean extraction seam should street work ever be split out (issue #99's
packaging decision). Catalog access is read-only for the core tables
(cities/runs); the package writes only its own `street_networks` rows.

Run it as a module:

    python -m streetscape_street_analyzer.analyze "Seattle, WA"
"""

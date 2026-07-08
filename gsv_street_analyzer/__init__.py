"""
gsv_street_analyzer — OSM street-coverage analysis for GSV Tracker (issue #24).

A standalone enrichment layer, separate from the main run pipeline: given an
existing run's pano CSV and a city's frozen grid geometry, it overlays the
OpenStreetMap drivable street network and decides, per street segment, whether
it has at least one nearby pano (a deliberately liberal definition — see
`street_coverage.compute_street_coverage`). Results are broken down by OSM
`highway` type and written as a published GeoJSON artifact for the web frontend.

Nothing here touches the catalog DB, cli, scheduler, or aggregate — it reads the
catalog read-only to resolve a city and locate its run file.
"""
import os
import sys

# Allow `import gsv_metadata_tracker` when a submodule is run directly
# (e.g. `python gsv_street_analyzer/analyze.py`); harmless when the repo root
# is already on sys.path (the `python -m gsv_street_analyzer.analyze` case).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

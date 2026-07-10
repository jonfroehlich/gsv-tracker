"""Geo helpers: OSM bounding-box midpoint used as the grid center (issue #91)."""

from geopy.location import Location

from streetscape_metadata_tracker.geoutils import EnhancedLocation


def _location(raw):
    """A minimal geopy Location wrapping a raw Nominatim result dict."""
    return Location("Somewhere", (0.0, 0.0, 0.0), raw)


def test_bbox_center_is_bounding_box_midpoint():
    # Nominatim boundingbox is [south, north, west, east]; the geocoder's own
    # point (0,0) is deliberately off-center to prove we don't use it.
    loc = EnhancedLocation(
        "Somewhere", _location({"boundingbox": ["10.0", "20.0", "30.0", "40.0"], "address": {}})
    )
    assert loc.bbox_center == (15.0, 35.0)  # ((10+20)/2, (30+40)/2)
    assert loc.latitude == 0.0  # not the source of the center


def test_bbox_center_none_without_bounding_box():
    loc = EnhancedLocation("Somewhere", _location({"address": {}}))
    assert loc.bbox_center is None

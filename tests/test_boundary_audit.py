"""
Boundary-audit tests (issue #91, step 1): bbox math, shoelace polygon
areas, Nominatim raw parsing, and the classify() verdict ladder. Pure
logic — no network, mirroring the failure modes the audit exists to catch
(Bancroft-SD-as-Le-Sueur-Township, neighborhood/admin-region bboxes).
"""

import math

import pytest

from gsv_metadata_tracker.boundary_audit import (
    Thresholds,
    bbox_dims_m,
    bbox_intersection_frac,
    classify,
    frozen_rect_bounds,
    parse_osm_result,
    polygon_area_m2,
    rect_polygon_coverage,
)
from gsv_metadata_tracker.db import CityRow


def make_city(center_lat=47.6, center_lon=-122.33, grid_width_m=10_000, grid_height_m=10_000):
    return CityRow(
        city_id="test--city",
        display_name="Test City",
        city_name="Test",
        state_name="Washington",
        state_code="WA",
        country_name="United States",
        country_code="US",
        center_lat=center_lat,
        center_lon=center_lon,
        grid_width_m=grid_width_m,
        grid_height_m=grid_height_m,
        step_m=20,
        created_at="2026-07-06T00:00:00+00:00",
        enabled=True,
        notes=None,
    )


def make_raw(
    south,
    north,
    west,
    east,
    geojson="polygon",
    lat=None,
    lon=None,
    display_name="Test, Washington, United States",
):
    """Synthetic Nominatim raw dict — boundingbox strings, like the API."""
    raw = {
        "display_name": display_name,
        "osm_type": "relation",
        "class": "boundary",
        "type": "administrative",
        "lat": str(lat if lat is not None else (south + north) / 2),
        "lon": str(lon if lon is not None else (west + east) / 2),
        "boundingbox": [str(south), str(north), str(west), str(east)],
    }
    if geojson == "polygon":
        raw["geojson"] = {
            "type": "Polygon",
            "coordinates": [
                [[west, south], [east, south], [east, north], [west, north], [west, south]]
            ],
        }
    elif geojson == "point":
        raw["geojson"] = {"type": "Point", "coordinates": [raw["lon"], raw["lat"]]}
    return raw


def square_ring(center_lat, center_lon, side_m):
    """Closed GeoJSON ring approximating a side_m × side_m square."""
    half_lat = (side_m / 2) / 110_540.0
    half_lon = (side_m / 2) / (111_320.0 * math.cos(math.radians(center_lat)))
    return [
        [center_lon - half_lon, center_lat - half_lat],
        [center_lon + half_lon, center_lat - half_lat],
        [center_lon + half_lon, center_lat + half_lat],
        [center_lon - half_lon, center_lat + half_lat],
        [center_lon - half_lon, center_lat - half_lat],
    ]


class TestBboxMath:
    def test_bbox_dims_at_equator(self):
        # 1 degree of longitude at the equator ~ 111.3 km
        w, h = bbox_dims_m((-0.5, 0.5, 10.0, 11.0))
        assert w == pytest.approx(111_320, rel=0.01)
        assert h == pytest.approx(110_540, rel=0.01)

    def test_bbox_width_shrinks_at_high_latitude(self):
        w_eq, _ = bbox_dims_m((-0.5, 0.5, 10.0, 11.0))
        w_60, _ = bbox_dims_m((59.5, 60.5, 10.0, 11.0))
        assert w_60 == pytest.approx(w_eq * math.cos(math.radians(60)), rel=0.02)

    @pytest.mark.parametrize("lat", [0.0, 47.6, -45.0])
    def test_frozen_rect_roundtrip(self, lat):
        rect = frozen_rect_bounds(lat, 10.0, 8_000, 6_000)
        w, h = bbox_dims_m(rect)
        assert w == pytest.approx(8_000, rel=0.01)
        assert h == pytest.approx(6_000, rel=0.01)

    def test_intersection_containment_disjoint_and_half(self):
        target = (0.0, 1.0, 0.0, 1.0)
        assert bbox_intersection_frac((-1, 2, -1, 2), target) == 1.0
        assert bbox_intersection_frac((5, 6, 5, 6), target) == 0.0
        assert bbox_intersection_frac((0.0, 0.5, 0.0, 1.0), target) == pytest.approx(0.5)

    def test_intersection_degenerate_target_is_zero(self):
        assert bbox_intersection_frac((0, 1, 0, 1), (2.0, 2.0, 5.0, 5.0)) == 0.0


class TestPolygonArea:
    @pytest.mark.parametrize("lat", [0.0, 60.0])
    def test_square_km_area(self, lat):
        geom = {"type": "Polygon", "coordinates": [square_ring(lat, 10.0, 1_000)]}
        assert polygon_area_m2(geom) == pytest.approx(1e6, rel=0.03)

    def test_hole_is_subtracted_and_winding_agnostic(self):
        outer = square_ring(0.0, 10.0, 1_000)
        hole = square_ring(0.0, 10.0, 500)
        geom = {"type": "Polygon", "coordinates": [outer, hole]}
        assert polygon_area_m2(geom) == pytest.approx(1e6 - 0.25e6, rel=0.03)
        geom_rev = {"type": "Polygon", "coordinates": [outer[::-1], hole[::-1]]}
        assert polygon_area_m2(geom_rev) == pytest.approx(polygon_area_m2(geom))

    def test_multipolygon_sums(self):
        geom = {
            "type": "MultiPolygon",
            "coordinates": [[square_ring(0.0, 10.0, 1_000)], [square_ring(0.0, 12.0, 1_000)]],
        }
        assert polygon_area_m2(geom) == pytest.approx(2e6, rel=0.03)

    @pytest.mark.parametrize(
        "geom",
        [
            None,
            {"type": "Point", "coordinates": [10.0, 0.0]},
            {"type": "LineString", "coordinates": [[10.0, 0.0], [11.0, 0.0]]},
            {"type": "GeometryCollection", "geometries": []},
        ],
    )
    def test_non_areal_geometry_is_none(self, geom):
        assert polygon_area_m2(geom) is None


class TestRectPolygonCoverage:
    """rect_polygon_coverage: fraction of a boundary polygon inside a grid."""

    def _poly(self, lat=0.0, lon=10.0, side_m=1_000):
        return {"type": "Polygon", "coordinates": [square_ring(lat, lon, side_m)]}

    def test_rect_fully_contains_polygon_is_one(self):
        poly = self._poly(side_m=1_000)
        big = frozen_rect_bounds(0.0, 10.0, 4_000, 4_000)
        assert rect_polygon_coverage(poly, big) == pytest.approx(1.0, abs=1e-6)

    def test_disjoint_rect_is_zero(self):
        poly = self._poly(lat=0.0, lon=10.0, side_m=1_000)
        away = frozen_rect_bounds(0.0, 20.0, 2_000, 2_000)
        assert rect_polygon_coverage(poly, away) == pytest.approx(0.0, abs=1e-6)

    def test_half_overlap_is_about_half(self):
        # Rect (same width) shifted east by the polygon's half-width (500 m)
        # leaves only the polygon's western half inside it.
        poly = self._poly(lat=0.0, lon=10.0, side_m=1_000)
        shift_lon = 500 / (111_320.0 * math.cos(math.radians(0.0)))
        shifted = frozen_rect_bounds(0.0, 10.0 + shift_lon, 1_000, 2_000)
        assert rect_polygon_coverage(poly, shifted) == pytest.approx(0.5, abs=0.02)

    def test_multipolygon_partial(self):
        # Two 1 km² squares; a rect over only one covers half the total area.
        geom = {
            "type": "MultiPolygon",
            "coordinates": [[square_ring(0.0, 10.0, 1_000)], [square_ring(0.0, 12.0, 1_000)]],
        }
        over_one = frozen_rect_bounds(0.0, 10.0, 3_000, 3_000)
        assert rect_polygon_coverage(geom, over_one) == pytest.approx(0.5, abs=0.02)

    @pytest.mark.parametrize(
        "geom,bbox",
        [
            (None, frozen_rect_bounds(0.0, 10.0, 1_000, 1_000)),
            (
                {"type": "Point", "coordinates": [10.0, 0.0]},
                frozen_rect_bounds(0.0, 10.0, 1_000, 1_000),
            ),
        ],
    )
    def test_no_polygon_or_bbox_is_none(self, geom, bbox):
        assert rect_polygon_coverage(geom, bbox) is None
        assert rect_polygon_coverage(self._poly(), None) is None


class TestParseOsmResult:
    def test_string_bbox_is_coerced(self):
        osm = parse_osm_result(make_raw(47.5, 47.7, -122.4, -122.2))
        assert osm.bbox == (47.5, 47.7, -122.4, -122.2)
        assert osm.geometry_type == "Polygon"
        assert osm.polygon_area_m2 is not None and osm.polygon_area_m2 > 0
        assert osm.place_class == "boundary"

    def test_missing_bbox_and_geojson_tolerated(self):
        raw = make_raw(47.5, 47.7, -122.4, -122.2)
        del raw["boundingbox"], raw["geojson"]
        osm = parse_osm_result(raw)
        assert osm.bbox is None
        assert osm.geometry_type is None
        assert osm.polygon_area_m2 is None


class TestClassify:
    # Frozen rectangle: 10x10 km centered on (47.6, -122.33); the OSM
    # bbox of a matching city is ~ the same rectangle
    MATCHING = frozen_rect_bounds(47.6, -122.33, 10_000, 10_000)

    def test_ok_when_rect_matches_osm_bbox(self):
        osm = parse_osm_result(make_raw(*self.MATCHING))
        assert classify(make_city(), osm).verdict == "OK"

    def test_not_found(self):
        assert classify(make_city(), None).verdict == "NOT_FOUND"

    def test_under_when_osm_bbox_much_larger(self):
        # Neighborhood-sized frozen rect inside a 3x-per-axis city bbox
        big = frozen_rect_bounds(47.6, -122.33, 30_000, 30_000)
        osm = parse_osm_result(make_raw(*big))
        res = classify(make_city(), osm)
        assert res.verdict == "UNDER"
        assert res.bbox_coverage_frac == pytest.approx(1 / 9, rel=0.05)
        assert res.suggested_width_m == pytest.approx(30_000, rel=0.01)
        assert res.suggested_height_m == pytest.approx(30_000, rel=0.01)

    def test_over_when_rect_is_admin_region_sized(self):
        # Frozen rect 40x40 km over a 10x10 km municipality
        osm = parse_osm_result(make_raw(*self.MATCHING))
        res = classify(make_city(grid_width_m=40_000, grid_height_m=40_000), osm)
        assert res.verdict == "OVER"
        assert res.over_area_ratio == pytest.approx(16.0, rel=0.05)

    def test_wrong_place_beats_size_verdicts(self):
        # Bancroft-style: frozen center hundreds of km from the OSM city
        osm = parse_osm_result(make_raw(44.0, 44.1, -94.0, -93.9))
        res = classify(make_city(center_lat=47.6, center_lon=-122.33), osm)
        assert res.verdict == "WRONG_PLACE"
        assert res.center_in_osm_bbox is False
        assert res.center_dist_km > 1_000

    def test_no_polygon_for_point_result(self):
        osm = parse_osm_result(make_raw(*self.MATCHING, geojson="point"))
        assert classify(make_city(), osm).verdict == "NO_POLYGON"

    def test_bbox_suspect_when_inverted_or_missing(self):
        # west > east (antimeridian-style artifact)
        osm = parse_osm_result(make_raw(47.5, 47.7, 170.0, -170.0))
        assert classify(make_city(), osm).verdict == "BBOX_SUSPECT"
        raw = make_raw(47.5, 47.7, -122.4, -122.2)
        del raw["boundingbox"]
        assert classify(make_city(), parse_osm_result(raw)).verdict == "BBOX_SUSPECT"

    def test_thresholds_are_tunable(self):
        big = frozen_rect_bounds(47.6, -122.33, 12_000, 12_000)
        osm = parse_osm_result(make_raw(*big))
        # coverage ~0.69: UNDER at the default 0.75, OK at 0.5
        assert classify(make_city(), osm).verdict == "UNDER"
        assert classify(make_city(), osm, Thresholds(min_coverage=0.5)).verdict == "OK"

    def test_degenerate_frozen_rect_is_under(self):
        # Real catalog case: an 8 m-wide junk rectangle
        osm = parse_osm_result(make_raw(*self.MATCHING))
        res = classify(make_city(grid_width_m=8, grid_height_m=8), osm)
        assert res.verdict == "UNDER"
        assert res.bbox_coverage_frac == pytest.approx(0.0, abs=1e-6)

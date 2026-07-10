"""Unit tests for the provider-agnostic download helpers extracted into
`download_common.py` (grid generation, capture-date normalization, the shared
download exception). These are consumed by both the GSV and Mapillary
downloaders and the GSV history harvester, so they're tested on their own here
rather than only transitively through a provider.
"""

import geopy.distance
import pytest

from streetscape_metadata_tracker.download_common import (
    DownloadError,
    generate_grid_points,
    standardize_capture_date,
)

SEATTLE = geopy.Point(47.6062, -122.3321)


# ── generate_grid_points ────────────────────────────────────────────────────


def test_grid_point_count_is_steps_plus_one_squared():
    # (width_steps + 1) * (height_steps + 1) — a fencepost point on each side.
    points = generate_grid_points(SEATTLE, width_steps=4, height_steps=6, step_length=20)
    assert len(points) == (4 + 1) * (6 + 1)


def test_grid_zero_steps_yields_single_centered_point():
    points = generate_grid_points(SEATTLE, width_steps=0, height_steps=0, step_length=20)
    assert len(points) == 1
    lat, lon, i, j = points[0]
    assert (i, j) == (0, 0)
    assert lat == pytest.approx(SEATTLE.latitude, abs=1e-9)
    assert lon == pytest.approx(SEATTLE.longitude, abs=1e-9)


def test_grid_center_point_is_the_origin():
    points = generate_grid_points(SEATTLE, width_steps=4, height_steps=4, step_length=50)
    center = [(lat, lon) for lat, lon, i, j in points if i == 0 and j == 0]
    assert len(center) == 1
    lat, lon = center[0]
    assert lat == pytest.approx(SEATTLE.latitude, abs=1e-9)
    assert lon == pytest.approx(SEATTLE.longitude, abs=1e-9)


def test_grid_indices_cover_the_full_rectangle():
    w, h = 4, 6
    points = generate_grid_points(SEATTLE, width_steps=w, height_steps=h, step_length=20)
    idx = {(i, j) for _, _, i, j in points}
    expected = {(i, j) for i in range(-h // 2, h // 2 + 1) for j in range(-w // 2, w // 2 + 1)}
    assert idx == expected


def test_grid_step_spacing_matches_step_length():
    step = 100
    points = generate_grid_points(SEATTLE, width_steps=2, height_steps=2, step_length=step)
    by_idx = {(i, j): (lat, lon) for lat, lon, i, j in points}
    # Neighbor one step east (j: 0 -> 1) should be ~step_length meters away.
    center = by_idx[(0, 0)]
    east = by_idx[(0, 1)]
    dist_m = geopy.distance.distance(center, east).meters
    assert dist_m == pytest.approx(step, rel=0.01)


# ── standardize_capture_date ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-05-15", "2024-05-15"),  # full date passes through
        ("2024-05", "2024-05-01"),  # year-month → first of month
        ("2024", "2024-01-01"),  # year only → Jan 1
        (None, None),  # missing
        ("", None),  # empty
        ("not-a-date", None),  # unparseable
        ("2024/05/15", None),  # slash format is not accepted
        ("05-15-2024", None),  # US ordering is not accepted
    ],
)
def test_standardize_capture_date(raw, expected):
    assert standardize_capture_date(raw) == expected


# ── DownloadError ───────────────────────────────────────────────────────────


def test_download_error_is_an_exception():
    assert issubclass(DownloadError, Exception)
    with pytest.raises(DownloadError, match="boom"):
        raise DownloadError("boom")

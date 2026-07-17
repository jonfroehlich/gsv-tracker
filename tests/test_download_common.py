"""Unit tests for the provider-agnostic download helpers extracted into
`download_common.py` (grid generation, capture-date normalization, the shared
download exception). These are consumed by both the GSV and Mapillary
downloaders and the GSV history harvester, so they're tested on their own here
rather than only transitively through a provider.
"""

import geopy.distance
import pytest

from streetscape_metadata_tracker.download_common import (
    AsyncRateLimiter,
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


def test_grid_coordinates_literal_anchor():
    """Pin exact output coordinates for one known grid.

    The other grid tests verify structure (counts, indices, relative
    spacing) — properties a mirrored bug in the implementation could still
    satisfy. These literals were hand-checked against independent geodesy:
    100 m north of 47.6°N is +0.000899° lat; 100 m east is +0.001330° lon
    (1° lon ≈ 75.1 km at that latitude). A regression in the bearing/
    distance math changes them and fails here.
    """
    points = generate_grid_points(SEATTLE, width_steps=2, height_steps=2, step_length=100)
    by_idx = {(i, j): (lat, lon) for lat, lon, i, j in points}
    assert by_idx[(1, 0)] == (
        pytest.approx(47.607099, abs=5e-6),
        pytest.approx(-122.332100, abs=5e-6),
    )
    assert by_idx[(0, 1)] == (
        pytest.approx(47.606200, abs=5e-6),
        pytest.approx(-122.330770, abs=5e-6),
    )
    assert by_idx[(-1, -1)] == (
        pytest.approx(47.605301, abs=5e-6),
        pytest.approx(-122.333430, abs=5e-6),
    )


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


# ── AsyncRateLimiter ────────────────────────────────────────────────────────
#
# Deterministic: the limiter takes an injectable clock (time_func) and its
# only sleep call is monkeypatched to advance that fake clock, so no test
# here waits on real time.


def _make_clock():
    clock = {"t": 0.0}
    return clock, (lambda: clock["t"])


def _patch_sleep(monkeypatch, clock, sleeps):
    import asyncio as aio

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(aio, "sleep", fake_sleep)


def _run(coro):
    import asyncio as aio

    return aio.run(coro)


def test_rate_limiter_paces_to_configured_rate(monkeypatch):
    clock, now = _make_clock()
    sleeps = []
    _patch_sleep(monkeypatch, clock, sleeps)
    limiter = AsyncRateLimiter(60, time_func=now)  # 1 token/s, burst 1

    async def scenario():
        for _ in range(3):
            await limiter.acquire()

    _run(scenario())
    # First acquisition spends the initial token; each subsequent one must
    # wait a full second for the next token to accrue.
    assert sleeps == [pytest.approx(1.0), pytest.approx(1.0)]


def test_rate_limiter_allows_one_second_burst(monkeypatch):
    clock, now = _make_clock()
    sleeps = []
    _patch_sleep(monkeypatch, clock, sleeps)
    limiter = AsyncRateLimiter(600, time_func=now)  # 10 tokens/s, burst 10

    async def scenario():
        for _ in range(10):
            await limiter.acquire()  # burst capacity: no waiting
        await limiter.acquire()  # 11th must wait one token interval

    _run(scenario())
    assert sleeps == [pytest.approx(0.1)]


def test_rate_limiter_refills_while_idle_but_caps_at_capacity(monkeypatch):
    clock, now = _make_clock()
    sleeps = []
    _patch_sleep(monkeypatch, clock, sleeps)
    limiter = AsyncRateLimiter(600, time_func=now)  # 10 tokens/s, burst 10

    async def scenario():
        for _ in range(10):
            await limiter.acquire()  # drain the bucket
        clock["t"] += 3600.0  # a long idle refills at most to capacity
        for _ in range(10):
            await limiter.acquire()  # burst again without waiting
        await limiter.acquire()  # ...but the 11th still waits

    _run(scenario())
    assert sleeps == [pytest.approx(0.1)]


def test_rate_limiter_zero_or_negative_disables(monkeypatch):
    clock, now = _make_clock()
    sleeps = []
    _patch_sleep(monkeypatch, clock, sleeps)

    async def scenario():
        for max_per_minute in (0, -5):
            limiter = AsyncRateLimiter(max_per_minute, time_func=now)
            for _ in range(100):
                await limiter.acquire()

    _run(scenario())
    assert sleeps == []

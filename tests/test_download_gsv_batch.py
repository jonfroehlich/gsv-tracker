"""End-to-end tests for the GSV batch downloader's quota-throttling behavior
(`download_gsv.py`), driven with a monkeypatched fetch primitive — the same
served-from-memory pattern as the Mapillary tests. No network.

Covers the 2026-07-16 incident class: Google signals per-minute quota
exhaustion as an HTTP 200 body with status OVER_QUERY_LIMIT. Such responses
say nothing about the grid point itself, so they must be retried and must
never be written to the immutable snapshot as final rows; a run left with
too many holes after retries must abort (keeping its resume checkpoint)
rather than register a clean-looking snapshot that silently lost coverage.
"""

import asyncio

import pytest

from streetscape_metadata_tracker import download_gsv as dg
from streetscape_metadata_tracker.download_common import DownloadError

CENTER_LAT, CENTER_LON = 44.05, -121.31

THROTTLED = {"status": "OVER_QUERY_LIMIT"}


def _ok_response(lat: float, lon: float) -> dict:
    return {
        "status": "OK",
        "location": {"lat": lat, "lng": lon},
        "pano_id": f"pano_{lat:.6f}_{lon:.6f}",
        "copyright": "© Google",
        "date": "2024-05",
    }


def _point_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 9), round(lon, 9))


def _patch_instant_retry_sleep(monkeypatch):
    """Skip the real inter-retry-pass waits (20s/40s/…) but keep yielding."""
    real_sleep = asyncio.sleep

    async def instant_sleep(seconds):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)


def _run_download(tmp_path, monkeypatch, fake_fetch, grid_m=40, **kwargs):
    """Drive the real download loop with `fake_fetch` as the API. A 40 m
    grid at step 20 is 3x3 = 9 points."""
    out = str(tmp_path / f"bend_width_{grid_m}_height_{grid_m}_step_20_2026-07-16.csv.gz")
    monkeypatch.setattr(dg, "fetch_gsv_pano_metadata_async", fake_fetch)
    result = asyncio.run(
        dg.download_gsv_metadata_async(
            city_name="Bend",
            center_lat=CENTER_LAT,
            center_lon=CENTER_LON,
            grid_width=grid_m,
            grid_height=grid_m,
            step_length=20,
            api_key="TESTKEY",
            output_csv_gz_path=out,
            batch_size=4,
            connection_limit=2,
            **kwargs,
        )
    )
    return result, out


def test_over_query_limit_is_retried_and_never_written(tmp_path, monkeypatch):
    """Every point throttled once, then OK: the run must end fully OK with
    no OVER_QUERY_LIMIT row, and the retry requests must be counted."""
    calls: dict[tuple, int] = {}
    seen_limiter = []

    async def fake_fetch(lat, lon, api_key, session, timeout, limiter=None):
        seen_limiter.append(limiter)
        key = _point_key(lat, lon)
        calls[key] = calls.get(key, 0) + 1
        if calls[key] == 1:
            return dict(THROTTLED)
        return _ok_response(lat, lon)

    # A limiter far above the request volume: verifies the wiring without
    # ever pacing (its 1-second burst capacity exceeds the whole run).
    result, out = _run_download(
        tmp_path, monkeypatch, fake_fetch, max_requests_per_minute=6_000_000
    )

    df = result["df"]
    assert len(df) == 9  # 3x3 grid, no dropped points
    assert set(df["status"]) == {"OK"}
    assert result["api_requests"] == 18  # 9 initial + 9 retried
    assert all(lim is not None for lim in seen_limiter), (
        "the run's rate limiter must reach every fetch, including retries"
    )


def test_persistent_throttle_aborts_and_keeps_checkpoint(tmp_path, monkeypatch):
    """All but one point throttled on every attempt: the run must refuse to
    finalize, keep the .downloading checkpoint for resume, and report the
    requests it spent (budget ledger)."""
    succeeded: set = set()

    async def fake_fetch(lat, lon, api_key, session, timeout, limiter=None):
        key = _point_key(lat, lon)
        if not succeeded or key in succeeded:
            succeeded.add(key)  # exactly one point ever succeeds
            return _ok_response(lat, lon)
        return dict(THROTTLED)

    _patch_instant_retry_sleep(monkeypatch)
    with pytest.raises(DownloadError) as excinfo:
        _run_download(tmp_path, monkeypatch, fake_fetch, max_requests_per_minute=0)

    assert "refusing to finalize" in str(excinfo.value)
    # 9 initial + 3 retry passes over the 8 still-throttled points
    assert excinfo.value.api_requests == 9 + 3 * 8

    base = "bend_width_40_height_40_step_20_2026-07-16"
    assert not (tmp_path / f"{base}.csv.gz").exists(), "no immutable snapshot may be finalized"
    assert (tmp_path / f"{base}.csv.downloading").exists(), "checkpoint must survive for resume"


def test_small_residual_failure_still_finalizes(tmp_path, monkeypatch):
    """One permanently failed point out of 121 (0.8% < the 1% threshold)
    keeps today's behavior: finalize without that point's row and record
    the stragglers in the failed-points sidecar."""
    unlucky: set = set()

    async def fake_fetch(lat, lon, api_key, session, timeout, limiter=None):
        key = _point_key(lat, lon)
        if not unlucky:
            unlucky.add(key)  # first point requested never succeeds
        if key in unlucky:
            return dict(THROTTLED)
        return _ok_response(lat, lon)

    _patch_instant_retry_sleep(monkeypatch)
    # 200 m grid at step 20 -> 11x11 = 121 points
    result, out = _run_download(
        tmp_path, monkeypatch, fake_fetch, grid_m=200, max_requests_per_minute=0
    )

    df = result["df"]
    assert len(df) == 120
    assert set(df["status"]) == {"OK"}
    assert result["api_requests"] == 121 + 3 * 1
    sidecar = tmp_path / "bend_width_200_height_200_step_20_2026-07-16_failed_points.csv"
    assert sidecar.exists()
    assert len(sidecar.read_text().strip().splitlines()) == 2  # header + 1 point

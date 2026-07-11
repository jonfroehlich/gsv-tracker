"""Run-level guards in download_gsv_metadata_async (audit 2026-07-11).

A scheduler run and a manual run of the same (city, provider, run_date)
used to share the same .downloading file and could silently overwrite a
registered, published snapshot with partial data. Both guards fire before
any network request, so these tests need no HTTP mocking.
"""

import asyncio

import pytest
from filelock import FileLock

from streetscape_metadata_tracker.download_common import DownloadError
from streetscape_metadata_tracker.download_gsv import download_gsv_metadata_async


def _run(out_path):
    return asyncio.run(
        download_gsv_metadata_async(
            city_name="Test City",
            center_lat=44.0,
            center_lon=-121.0,
            grid_width=100,
            grid_height=100,
            step_length=20,
            api_key="unused-guards-fire-first",
            output_csv_gz_path=str(out_path),
        )
    )


def test_refuses_to_overwrite_existing_snapshot(tmp_path):
    out = tmp_path / "t_width_100_height_100_step_20_2026-07-01.csv.gz"
    out.write_bytes(b"registered snapshot")
    with pytest.raises(DownloadError, match="refusing to overwrite"):
        _run(out)
    assert out.read_bytes() == b"registered snapshot", "existing snapshot untouched"


def test_refuses_concurrent_run_on_same_output(tmp_path):
    out = tmp_path / "t_width_100_height_100_step_20_2026-07-01.csv.gz"
    # Simulate another process mid-run: it holds the run-level lock.
    other = FileLock(
        str(tmp_path / "t_width_100_height_100_step_20_2026-07-01.csv.downloading.runlock")
    )
    other.acquire()
    try:
        with pytest.raises(DownloadError, match="[Aa]nother process"):
            _run(out)
    finally:
        other.release()

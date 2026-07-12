"""GSV resume-path tests: the .downloading checkpoint contract.

The resume filter matches (query_lat, query_lon) parsed back from the
checkpoint CSV against freshly regenerated grid floats. The CSV round-trip
can perturb a coordinate by a few ULP (pandas' fast CSV float parser does
not exactly round-trip every 17-digit decimal) — raw float equality
therefore re-requested already-paid-for points. Matching goes through
resume_point_key() (9-decimal quantization); these tests pin that contract
end-to-end through the real writer/reader defaults.
"""

import geopy
import pandas as pd

from streetscape_metadata_tracker.config import METADATA_DTYPES
from streetscape_metadata_tracker.download_common import generate_grid_points
from streetscape_metadata_tracker.download_gsv import get_processed_points, resume_point_key

SEATTLE = geopy.Point(47.6062, -122.3321)


def _checkpoint_df(points):
    """A minimal checkpoint frame: ZERO_RESULTS rows for the given grid points."""
    rows = [
        {
            "query_lat": lat,
            "query_lon": lon,
            "query_timestamp": "2026-07-11T00:00:00+00:00",
            "pano_lat": None,
            "pano_lon": None,
            "pano_id": None,
            "capture_date": None,
            "copyright_info": None,
            "status": "ZERO_RESULTS",
        }
        for lat, lon, _i, _j in points
    ]
    return pd.DataFrame(rows, columns=list(METADATA_DTYPES))


def test_processed_points_match_regenerated_grid_through_csv_round_trip(tmp_path):
    points = generate_grid_points(SEATTLE, width_steps=6, height_steps=6, step_length=20)
    done, remaining = points[:20], points[20:]

    path = tmp_path / "city.csv.downloading"
    # Same writer defaults as process_batch_async's df.to_csv(...)
    _checkpoint_df(done).to_csv(path, index=False)

    processed = get_processed_points(str(path))
    # Every checkpointed point matches its regenerated grid float via the
    # quantized key — this is exactly where raw equality used to fail
    assert processed == {resume_point_key(lat, lon) for lat, lon, _i, _j in done}
    # ...and none of the outstanding points are falsely marked done
    assert all(resume_point_key(lat, lon) not in processed for lat, lon, _i, _j in remaining)


def test_resume_point_key_absorbs_ulp_noise_but_separates_neighbors():
    lon = -122.33156803045203
    lon_perturbed = -122.33156803045205  # the actual CSV round-trip artifact
    assert resume_point_key(47.6, lon) == resume_point_key(47.6, lon_perturbed)
    # Neighboring grid points (20 m ≈ 2.7e-4° lon) stay distinct
    assert resume_point_key(47.6, lon) != resume_point_key(47.6, lon + 0.00027)


def test_processed_points_missing_file_is_empty(tmp_path):
    assert get_processed_points(str(tmp_path / "never-written.csv.downloading")) == set()


def test_processed_points_unreadable_file_is_empty(tmp_path):
    # A truncated/garbage checkpoint must degrade to "resume from zero",
    # not crash the run
    p = tmp_path / "corrupt.csv.downloading"
    p.write_bytes(b"\x00\x01\x02 not a csv \xff")
    assert get_processed_points(str(p)) == set()

"""
Coverage-definition tests (issue #90).

coverage_rate must be grid-point coverage — points with >= 1 pano / total
points — not unique-panos / points. The unique-based rate is a density
proxy: it collapses as the sampling step shrinks (duplicate snaps) and
made every city's coverage appear to plummet vs the published site.
"""

from datetime import date

import pandas as pd

from streetscape_metadata_tracker.analysis import (
    calculate_coverage_stats,
    calculate_pano_stats,
    calculate_run_stats,
)
from tests.conftest import COLUMNS, make_city_df, make_mapillary_city_df


class TestCalculateCoverageStats:
    def test_gsv_duplicate_panos_do_not_reduce_coverage(self):
        # 3 OK points but only 2 unique panos (adjacent points snapped to
        # the same pano) + 2 empty points: coverage is 3/5, not 2/5
        df = make_city_df(
            [("a", "2020-01-01"), ("a", "2020-01-01"), ("b", "2021-01-01")], n_empty=2
        )
        cov = calculate_coverage_stats(df)
        assert cov.num_points_with_panos == 3
        assert cov.num_points_without_panos == 2
        assert cov.num_points_with_errors == 0
        assert cov.num_points_with_unique_pano_ids == 2  # separate metric
        assert abs(cov.coverage_rate - 60.0) < 1e-9

    def test_error_rows_count_as_error_points(self):
        # A NO_DATE-only point holds present-but-dateless imagery, so it
        # counts as covered; only genuine errors (REQUEST_DENIED) are errors.
        ts = "2026-01-15T12:00:00+00:00"
        df = pd.DataFrame(
            [
                (44.000, -121.0, ts, 44.0001, -121.0001, "a", "2020-01-01", "© Google", "OK"),
                (44.001, -121.0, ts, None, None, None, None, None, "ZERO_RESULTS"),
                (44.002, -121.0, ts, None, None, None, None, None, "REQUEST_DENIED"),
                (44.003, -121.0, ts, 44.0031, -121.0031, "d", None, "© Google", "NO_DATE"),
            ],
            columns=COLUMNS,
        )
        cov = calculate_coverage_stats(df)
        assert cov.num_points_with_panos == 2  # OK + NO_DATE
        assert cov.num_points_without_panos == 1  # ZERO_RESULTS
        assert cov.num_points_with_errors == 1  # REQUEST_DENIED
        assert cov.num_points_with_unique_pano_ids == 2  # dateless pano counts
        assert abs(cov.coverage_rate - 50.0) < 1e-9

    def test_mapillary_census_rows_count_grid_points_once(self):
        # 6 panos on 2 grid points (3 rows each) + 1 empty point:
        # coverage is 2/3 points, while unique panos stays a census count
        df = make_mapillary_city_df([(f"m{i}", "2022-01-01") for i in range(6)], panos_per_point=3)
        cov = calculate_coverage_stats(df)
        assert cov.num_points_with_panos == 2
        assert cov.num_points_without_panos == 1
        assert cov.num_points_with_unique_pano_ids == 6
        assert abs(cov.coverage_rate - 100 * 2 / 3) < 1e-9

    def test_mapillary_point_with_both_ok_and_no_date_rows_is_covered(self):
        # A grid point holding an OK pano and a NO_DATE pano is covered,
        # not an error point
        ts = "2026-01-15T12:00:00+00:00"
        df = pd.DataFrame(
            [
                (44.0, -121.0, ts, 44.0001, -121.0001, "m1", "2022-01-01", "© contributor", "OK"),
                (44.0, -121.0, ts, 44.0002, -121.0002, "m2", None, "© contributor", "NO_DATE"),
                (44.001, -121.0, ts, None, None, None, None, None, "ZERO_RESULTS"),
            ],
            columns=COLUMNS,
        )
        cov = calculate_coverage_stats(df)
        assert cov.num_points_with_panos == 1
        assert cov.num_points_without_panos == 1
        assert cov.num_points_with_errors == 0
        assert abs(cov.coverage_rate - 50.0) < 1e-9

    def test_empty_frame_is_zero_coverage(self):
        df = pd.DataFrame([], columns=COLUMNS)
        cov = calculate_coverage_stats(df)
        assert cov.coverage_rate == 0
        assert cov.num_points_with_panos == 0


class TestCatalogedCoverageRate:
    def test_run_stats_store_point_coverage_for_gsv(self):
        df = make_city_df(
            [("a", "2020-01-01"), ("a", "2020-01-01"), ("b", "2021-01-01")], n_empty=2
        )
        stats = calculate_run_stats(df, date(2026, 1, 15))
        # For GSV (one row per point) with no NO_DATE panos this equals
        # (status_ok + status_no_date) / total_points == status_ok / total.
        assert abs(stats["coverage_rate_pct"] - 60.0) < 1e-9
        assert (
            abs(
                stats["coverage_rate_pct"]
                - 100.0 * (stats["status_ok"] + stats["status_no_date"]) / stats["total_points"]
            )
            < 1e-9
        )

    def test_run_stats_store_point_coverage_for_mapillary(self):
        df = make_mapillary_city_df([(f"m{i}", "2022-01-01") for i in range(6)], panos_per_point=3)
        stats = calculate_run_stats(df, date(2026, 1, 15), provider="mapillary")
        # Rows are per-pano here, so the point rate must NOT be the row
        # rate (6 OK rows / 7 rows)
        assert stats["status_ok"] == 6 and stats["total_points"] == 7
        assert abs(stats["coverage_rate_pct"] - 100 * 2 / 3) < 1e-9


class TestNoDateCountsAsPresent:
    """A pano the provider returned but couldn't date (NO_DATE) is present
    imagery: it counts toward coverage and pano totals, never toward age
    stats, and is not an error point (schema v3)."""

    def _gsv_df_with_no_date(self):
        # 1 dated OK pano, 1 dateless NO_DATE pano (both © Google), 1 empty
        ts = "2026-01-15T12:00:00+00:00"
        return pd.DataFrame(
            [
                (44.000, -121.0, ts, 44.0001, -121.0001, "ok1", "2020-06-01", "© Google", "OK"),
                (44.001, -121.0, ts, 44.0011, -121.0011, "nd1", None, "© Google", "NO_DATE"),
                (44.002, -121.0, ts, None, None, None, None, None, "ZERO_RESULTS"),
            ],
            columns=COLUMNS,
        )

    def test_run_stats_counts_no_date_as_pano_and_coverage(self):
        stats = calculate_run_stats(self._gsv_df_with_no_date(), date(2026, 1, 15))
        assert stats["status_ok"] == 1
        assert stats["status_no_date"] == 1
        assert stats["status_zero_results"] == 1
        assert stats["status_other"] == 0
        assert stats["unique_panos"] == 2  # OK + NO_DATE both counted
        assert stats["unique_google_panos"] == 2  # both © Google
        assert abs(stats["coverage_rate_pct"] - 100 * 2 / 3) < 1e-9

    def test_no_date_pano_excluded_from_age_stats(self):
        stats = calculate_run_stats(self._gsv_df_with_no_date(), date(2026, 1, 15))
        # Age reflects only the single dated pano (2020-06-01); the dateless
        # pano must not skew or nullify it.
        assert stats["median_pano_age_years"] is not None
        assert stats["oldest_capture_date"] == stats["newest_capture_date"]
        assert stats["oldest_capture_date"].startswith("2020-06-01")

    def test_pano_stats_total_and_histogram(self):
        results = calculate_pano_stats(self._gsv_df_with_no_date(), pd.Timestamp("2026-01-15"))
        # Website headline pano count is sourced from here — must include the
        # dateless pano.
        assert results.duplicate_stats.total_unique_panos == 2
        # Capture-year histogram is date-based, so it sees only the OK pano.
        assert results.yearly_distribution.counts == {2020: 1}

    def test_point_with_only_no_date_is_covered_not_error(self):
        # A grid point whose sole pano is dateless is covered, not an error.
        ts = "2026-01-15T12:00:00+00:00"
        df = pd.DataFrame(
            [
                (44.000, -121.0, ts, 44.0001, -121.0001, "nd1", None, "© Google", "NO_DATE"),
                (44.001, -121.0, ts, None, None, None, None, None, "ZERO_RESULTS"),
            ],
            columns=COLUMNS,
        )
        cov = calculate_coverage_stats(df)
        assert cov.num_points_with_panos == 1
        assert cov.num_points_with_errors == 0
        assert cov.num_points_with_unique_pano_ids == 1
        assert abs(cov.coverage_rate - 50.0) < 1e-9

    def test_dateless_mapillary_pano_counts_in_census(self):
        # Mapillary census: a point with 2 panos, one of them dateless, still
        # contributes both panos to the unique count and is covered.
        ts = "2026-01-15T12:00:00+00:00"
        df = pd.DataFrame(
            [
                (
                    44.0,
                    -121.0,
                    ts,
                    44.0001,
                    -121.0001,
                    "m1",
                    "2022-01-01",
                    "© Mapillary contributor 1",
                    "OK",
                ),
                (
                    44.0,
                    -121.0,
                    ts,
                    44.0002,
                    -121.0002,
                    "m2",
                    None,
                    "© Mapillary contributor 2",
                    "NO_DATE",
                ),
            ],
            columns=COLUMNS,
        )
        stats = calculate_run_stats(df, date(2026, 1, 15), provider="mapillary")
        assert stats["unique_panos"] == 2
        assert stats["status_no_date"] == 1
        assert stats["unique_google_panos"] is None  # non-GSV
        assert abs(stats["coverage_rate_pct"] - 100.0) < 1e-9


class TestPanoStatsCoverage:
    def test_google_only_summary_keeps_run_level_coverage(self):
        # The google_only filter drops ZERO_RESULTS rows (null copyright);
        # coverage must still describe the whole sampled grid
        df = make_city_df([("a", "2020-01-01"), ("b", "2021-01-01")], n_empty=1)
        results = calculate_pano_stats(df, pd.Timestamp("2026-01-15"), google_only=True)
        cov = results.coverage_stats
        assert cov.num_points_without_panos == 1
        assert abs(cov.coverage_rate - 100 * 2 / 3) < 1e-9

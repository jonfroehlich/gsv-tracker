"""
Coverage-definition tests (issue #90).

coverage_rate must be grid-point coverage — points with >= 1 pano / total
points — not unique-panos / points. The unique-based rate is a density
proxy: it collapses as the sampling step shrinks (duplicate snaps) and
made every city's coverage appear to plummet vs the published site.
"""

from datetime import date

import pandas as pd

from gsv_metadata_tracker.analysis import (
    calculate_coverage_stats,
    calculate_pano_stats,
    calculate_run_stats,
)
from tests.conftest import COLUMNS, make_city_df, make_mapillary_city_df


class TestCalculateCoverageStats:

    def test_gsv_duplicate_panos_do_not_reduce_coverage(self):
        # 3 OK points but only 2 unique panos (adjacent points snapped to
        # the same pano) + 2 empty points: coverage is 3/5, not 2/5
        df = make_city_df([('a', '2020-01-01'), ('a', '2020-01-01'),
                           ('b', '2021-01-01')], n_empty=2)
        cov = calculate_coverage_stats(df)
        assert cov.num_points_with_panos == 3
        assert cov.num_points_without_panos == 2
        assert cov.num_points_with_errors == 0
        assert cov.num_points_with_unique_pano_ids == 2  # separate metric
        assert abs(cov.coverage_rate - 60.0) < 1e-9

    def test_error_rows_count_as_error_points(self):
        ts = '2026-01-15T12:00:00+00:00'
        df = pd.DataFrame([
            (44.000, -121.0, ts, 44.0001, -121.0001, 'a', '2020-01-01',
             '© Google', 'OK'),
            (44.001, -121.0, ts, None, None, None, None, None,
             'ZERO_RESULTS'),
            (44.002, -121.0, ts, None, None, None, None, None,
             'REQUEST_DENIED'),
            (44.003, -121.0, ts, None, None, None, None, None, 'NO_DATE'),
        ], columns=COLUMNS)
        cov = calculate_coverage_stats(df)
        assert cov.num_points_with_panos == 1
        assert cov.num_points_without_panos == 1
        assert cov.num_points_with_errors == 2
        assert abs(cov.coverage_rate - 25.0) < 1e-9

    def test_mapillary_census_rows_count_grid_points_once(self):
        # 6 panos on 2 grid points (3 rows each) + 1 empty point:
        # coverage is 2/3 points, while unique panos stays a census count
        df = make_mapillary_city_df(
            [(f'm{i}', '2022-01-01') for i in range(6)], panos_per_point=3)
        cov = calculate_coverage_stats(df)
        assert cov.num_points_with_panos == 2
        assert cov.num_points_without_panos == 1
        assert cov.num_points_with_unique_pano_ids == 6
        assert abs(cov.coverage_rate - 100 * 2 / 3) < 1e-9

    def test_mapillary_point_with_both_ok_and_no_date_rows_is_covered(self):
        # A grid point holding an OK pano and a NO_DATE pano is covered,
        # not an error point
        ts = '2026-01-15T12:00:00+00:00'
        df = pd.DataFrame([
            (44.0, -121.0, ts, 44.0001, -121.0001, 'm1', '2022-01-01',
             '© contributor', 'OK'),
            (44.0, -121.0, ts, 44.0002, -121.0002, 'm2', None,
             '© contributor', 'NO_DATE'),
            (44.001, -121.0, ts, None, None, None, None, None,
             'ZERO_RESULTS'),
        ], columns=COLUMNS)
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
        df = make_city_df([('a', '2020-01-01'), ('a', '2020-01-01'),
                           ('b', '2021-01-01')], n_empty=2)
        stats = calculate_run_stats(df, date(2026, 1, 15))
        # For GSV (one row per point) this equals status_ok / total_points,
        # which is exactly what scripts/recompute_coverage_rates.py applies
        assert abs(stats['coverage_rate_pct'] - 60.0) < 1e-9
        assert abs(stats['coverage_rate_pct']
                   - 100.0 * stats['status_ok'] / stats['total_points']) < 1e-9

    def test_run_stats_store_point_coverage_for_mapillary(self):
        df = make_mapillary_city_df(
            [(f'm{i}', '2022-01-01') for i in range(6)], panos_per_point=3)
        stats = calculate_run_stats(df, date(2026, 1, 15),
                                    provider='mapillary')
        # Rows are per-pano here, so the point rate must NOT be the row
        # rate (6 OK rows / 7 rows)
        assert stats['status_ok'] == 6 and stats['total_points'] == 7
        assert abs(stats['coverage_rate_pct'] - 100 * 2 / 3) < 1e-9


class TestPanoStatsCoverage:

    def test_google_only_summary_keeps_run_level_coverage(self):
        # The google_only filter drops ZERO_RESULTS rows (null copyright);
        # coverage must still describe the whole sampled grid
        df = make_city_df([('a', '2020-01-01'), ('b', '2021-01-01')],
                          n_empty=1)
        results = calculate_pano_stats(df, pd.Timestamp('2026-01-15'),
                                       google_only=True)
        cov = results.coverage_stats
        assert cov.num_points_without_panos == 1
        assert abs(cov.coverage_rate - 100 * 2 / 3) < 1e-9

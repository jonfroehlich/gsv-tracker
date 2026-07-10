"""Diff engine tests: pano set algebra, date changes, coverage transitions."""

from datetime import date

import pandas as pd

from gsv_metadata_tracker.diff import compute_run_diff, generate_diff_filename
from tests.conftest import COLUMNS, make_city_df


def _two_point_df(point_b_status, point_b_pano, point_b_date):
    """Grid of two points: A always holds an OK pano; B varies by status."""
    ts = '2026-01-15T12:00:00+00:00'
    rows = [(44.000, -121.0, ts, 44.0001, -121.0001, 'a', '2020-01-01',
             '© Google', 'OK')]
    if point_b_status == 'ZERO_RESULTS':
        rows.append((44.001, -121.0, ts, None, None, None, None, None,
                     'ZERO_RESULTS'))
    else:
        rows.append((44.001, -121.0, ts, 44.0011, -121.0011, point_b_pano,
                     point_b_date, '© Google', point_b_status))
    return pd.DataFrame(rows, columns=COLUMNS)


def test_no_changes_between_identical_runs():
    df = make_city_df([('p1', '2020-05-01'), ('p2', '2021-06-01')])
    d = compute_run_diff(df, df.copy())
    assert not d.has_changes
    assert d.panos_persisted == 2
    assert d.grid_aligned and d.coverage_delta_pct == 0.0
    assert len(d.detail) == 0


def test_added_removed_and_date_changed():
    old = make_city_df([('p1', '2020-05-01'), ('p2', '2021-06-01')])
    new = make_city_df([('p1', '2024-08-01'),   # re-dated
                        ('p3', '2025-01-01')])  # p2 removed, p3 added
    d = compute_run_diff(old, new)
    assert (d.panos_added, d.panos_removed, d.panos_persisted) == (1, 1, 1)
    assert d.capture_date_changed == 1
    assert set(d.detail['change_type']) == {'pano_added', 'pano_removed',
                                            'capture_date_changed'}
    row = d.detail[d.detail['change_type'] == 'capture_date_changed'].iloc[0]
    assert row['old_capture_date'] == '2020-05-01'
    assert row['new_capture_date'] == '2024-08-01'


def test_coverage_transitions_on_aligned_grid():
    # 2 panos + 1 empty point vs 3 panos + 0 empty on the same 3-point grid
    old = make_city_df([('p1', '2020-05-01'), ('p2', '2021-06-01')], n_empty=1)
    new = make_city_df([('p1', '2020-05-01'), ('p2', '2021-06-01'),
                        ('p3', '2025-01-01')], n_empty=0)
    d = compute_run_diff(old, new)
    assert d.grid_aligned
    assert d.points_gained_coverage == 1 and d.points_lost_coverage == 0
    assert abs(d.coverage_delta_pct - 100 / 3) < 1e-9


def test_no_date_point_gains_coverage():
    # Point B goes ZERO_RESULTS -> NO_DATE: dateless imagery appeared, so the
    # point is now covered (schema v3).
    old = _two_point_df('ZERO_RESULTS', None, None)
    new = _two_point_df('NO_DATE', 'b', None)
    d = compute_run_diff(old, new)
    assert d.grid_aligned
    assert d.points_gained_coverage == 1 and d.points_lost_coverage == 0
    assert abs(d.coverage_delta_pct - 50.0) < 1e-9


def test_no_date_point_lost_coverage():
    # Reverse: NO_DATE -> ZERO_RESULTS is a loss of coverage.
    old = _two_point_df('NO_DATE', 'b', None)
    new = _two_point_df('ZERO_RESULTS', None, None)
    d = compute_run_diff(old, new)
    assert d.points_gained_coverage == 0 and d.points_lost_coverage == 1
    assert abs(d.coverage_delta_pct + 50.0) < 1e-9


def test_misaligned_grid_skips_point_stats():
    old = make_city_df([('p1', '2020-05-01')])
    new = make_city_df([('p1', '2020-05-01')], grid_origin=(45.0, -120.0))
    d = compute_run_diff(old, new)
    assert not d.grid_aligned
    assert d.points_gained_coverage is None
    assert d.coverage_delta_pct is None
    # Pano-level diff still works
    assert d.panos_persisted == 1


def test_duplicate_pano_ids_deduped_keeping_newest_date():
    old = make_city_df([('p1', '2020-05-01'), ('p1', '2022-03-01')])
    new = make_city_df([('p1', '2022-03-01')])
    d = compute_run_diff(old, new)
    assert d.panos_persisted == 1
    assert d.capture_date_changed == 0  # newest old date matches new date


def test_diff_filename():
    assert generate_diff_filename('bend--or', '2026-04-01', '2026-07-01') == \
        'bend--or_diff_2026-04-01_to_2026-07-01.csv.gz'


def test_diff_filename_provider():
    # gsv keeps the tokenless legacy form; other providers get a token
    assert generate_diff_filename('bend--or', '2026-04-01', '2026-07-01',
                                  provider='gsv') == \
        'bend--or_diff_2026-04-01_to_2026-07-01.csv.gz'
    assert generate_diff_filename('bend--or', '2026-04-01', '2026-07-01',
                                  provider='mapillary') == \
        'bend--or_diff_mapillary_2026-04-01_to_2026-07-01.csv.gz'

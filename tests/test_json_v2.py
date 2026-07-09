"""JSON schema v2 tests: shape, NaN-free output, run_date-pinned ages."""

import gzip
import json
import os
from datetime import date

import pandas as pd
import pytest

from gsv_metadata_tracker import db
from gsv_metadata_tracker.fileutils import load_city_csv_file
from gsv_metadata_tracker.json_summarizer import (
    generate_aggregate_v2, generate_city_metadata_summary_as_json,
    sanitize_for_json)
from tests.conftest import (COLUMNS, make_city_df, make_mapillary_city_df,
                            write_city_csv_gz)


def strict_load(path):
    """json.load that raises on NaN/Infinity literals."""
    def _reject(token):
        raise ValueError(f"invalid token {token}")
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f, parse_constant=_reject)


def _write_run(data_dir, panos, run_date, name):
    csv_path = os.path.join(data_dir, name)
    write_city_csv_gz(make_city_df(panos, run_date=run_date), csv_path)
    return csv_path


def test_sanitize_for_json():
    dirty = {'a': float('nan'), 'b': [float('inf'), 1.5], 'c': {'d': float('-inf')}}
    clean = sanitize_for_json(dirty)
    assert clean == {'a': None, 'b': [None, 1.5], 'c': {'d': None}}
    json.dumps(clean, allow_nan=False)  # must not raise


def test_single_pano_city_emits_valid_json(data_dir):
    # Regression: 1 unique pano -> stdev NaN -> literal NaN in the JSON
    csv_path = _write_run(data_dir, [('p1', '2020-05-01')], date(2026, 1, 15),
                          'solo--city_width_100_height_100_step_20_2026-01-15.csv.gz')
    df = load_city_csv_file(csv_path)
    json_path = generate_city_metadata_summary_as_json(
        csv_path, df, 'Solo', None, 'Testland', 100, 100, 20,
        force_recreate_file=True, run_date=date(2026, 1, 15))
    data = strict_load(json_path)  # raises if NaN leaked
    assert data['all_panos']['age_stats']['stdev_pano_age_years'] is None


def test_no_date_pano_counted_in_json(data_dir):
    # End-to-end: a dateless (NO_DATE) pano must appear in the published pano
    # total and coverage, but not perturb the age stats (schema v3).
    ts = '2026-01-15T12:00:00+00:00'
    df_raw = pd.DataFrame([
        (44.000, -121.0, ts, 44.0001, -121.0001, 'ok1', '2020-01-15',
         '© Google', 'OK'),
        (44.001, -121.0, ts, 44.0011, -121.0011, 'nd1', None,
         '© Google', 'NO_DATE'),
        (44.002, -121.0, ts, None, None, None, None, None, 'ZERO_RESULTS'),
    ], columns=COLUMNS)
    csv_path = os.path.join(
        data_dir, 'nd--city_width_100_height_100_step_20_2026-01-15.csv.gz')
    write_city_csv_gz(df_raw, csv_path)
    df = load_city_csv_file(csv_path)
    json_path = generate_city_metadata_summary_as_json(
        csv_path, df, 'ND', None, 'Testland', 100, 100, 20,
        force_recreate_file=True, run_date=date(2026, 1, 15))
    data = strict_load(json_path)

    # Both panos counted; Google subset counts the dateless © Google pano too
    assert data['all_panos']['duplicate_stats']['total_unique_panos'] == 2
    assert data['google_panos']['duplicate_stats']['total_unique_panos'] == 2
    # Coverage: 2 of 3 grid points hold imagery
    assert data['coverage']['coverage_rate'] == pytest.approx(100 * 2 / 3)
    # Age stats derive from the single dated pano (captured exactly 6y before)
    assert data['all_panos']['age_stats']['avg_pano_age_years'] == \
        pytest.approx(6.0, abs=0.01)


def test_v2_fields_and_age_pinned_to_run_date(data_dir):
    run_date = date(2026, 1, 15)
    csv_path = _write_run(data_dir, [('p1', '2020-01-15'), ('p2', '2022-01-15')],
                          run_date,
                          'duo--city_width_100_height_100_step_20_2026-01-15.csv.gz')
    df = load_city_csv_file(csv_path)
    change = {"from_run_date": "2025-10-01", "panos_added": 1, "panos_removed": 0,
              "capture_date_changed": 0, "coverage_delta_pct": 0.0,
              "grid_aligned": True, "diff_file": None}
    json_path = generate_city_metadata_summary_as_json(
        csv_path, df, 'Duo', None, 'Testland', 100, 100, 20,
        force_recreate_file=True, run_date=run_date,
        change_from_previous_run=change)
    data = strict_load(json_path)

    assert data['schema_version'] == 2
    assert data['provider'] == 'gsv'
    assert data['run'] == {'run_date': '2026-01-15', 'is_baseline': False}
    assert data['change_from_previous_run']['panos_added'] == 1
    assert 'google_panos' in data
    assert data['copyright_info_available'] is True

    # Ages relative to run_date: panos captured exactly 6 and 4 years earlier
    ages = data['all_panos']['age_stats']
    assert ages['avg_pano_age_years'] == pytest.approx(5.0, abs=0.01)
    assert ages['median_pano_age_years'] == pytest.approx(5.0, abs=0.01)


def test_copyright_unknown_run_json(data_dir):
    # Archival imports (issue #93) never captured copyright_info: the
    # Google subset is unknown, so google_panos is omitted and flagged
    run_date = date(2023, 11, 5)
    csv_path = os.path.join(
        data_dir, 'old--city_width_1000_height_1000_step_30_2023-11-05.csv.gz')
    write_city_csv_gz(make_city_df([('p1', '2020-05-01'), ('p2', '2021-06-01')],
                                   run_date=run_date, copyright_info=None),
                      csv_path)
    df = load_city_csv_file(csv_path)
    json_path = generate_city_metadata_summary_as_json(
        csv_path, df, 'Old', None, 'Testland', 1000, 1000, 30,
        force_recreate_file=True, run_date=run_date, is_baseline=True)
    data = strict_load(json_path)

    assert data['copyright_info_available'] is False
    assert 'google_panos' not in data
    assert data['run'] == {'run_date': '2023-11-05', 'is_baseline': True}
    assert data['all_panos']['duplicate_stats']['total_unique_panos'] == 2


def test_run_stats_google_panos_none_when_copyright_unknown():
    from gsv_metadata_tracker.analysis import calculate_run_stats

    run_date = date(2023, 11, 5)
    df_unknown = make_city_df([('p1', '2020-05-01')], run_date=run_date,
                              copyright_info=None)
    stats = calculate_run_stats(df_unknown, run_date)
    assert stats['unique_google_panos'] is None
    assert stats['unique_panos'] == 1

    df_known = make_city_df([('p1', '2020-05-01')], run_date=run_date)
    stats = calculate_run_stats(df_known, run_date)
    assert stats['unique_google_panos'] == 1

    # A run with zero OK rows has a trivially known (zero) Google subset
    df_empty = make_city_df([], run_date=run_date, n_empty=2)
    stats = calculate_run_stats(df_empty, run_date)
    assert stats['unique_google_panos'] == 0


def test_aggregate_propagates_copyright_flag(conn, data_dir):
    city_id = db.register_city(
        conn, city_name='Old', state_name=None, state_code=None,
        country_name='Testland', country_code=None,
        center_lat=44.0, center_lon=-121.0,
        grid_width_m=1000, grid_height_m=1000, step_m=20)
    run_date = date(2023, 11, 5)
    csv_name = f'{city_id}_width_1000_height_1000_step_30_2023-11-05.csv.gz'
    csv_path = os.path.join(data_dir, csv_name)
    write_city_csv_gz(make_city_df([('p1', '2020-05-01')], run_date=run_date,
                                   copyright_info=None), csv_path)
    df = load_city_csv_file(csv_path)
    json_path = generate_city_metadata_summary_as_json(
        csv_path, df, 'Old', None, 'Testland', 1000, 1000, 30,
        force_recreate_file=True, run_date=run_date, is_baseline=True)
    db.register_run(conn, city_id=city_id, run_date=run_date,
                    csv_filename=csv_name,
                    json_filename=os.path.basename(json_path),
                    is_baseline=True, unique_panos=1,
                    unique_google_panos=None)

    summary = generate_aggregate_v2(conn, data_dir)
    gsv = summary['cities'][0]['providers']['gsv']

    assert gsv['latest']['copyright_info_available'] is False
    assert 'unique_google_panos' not in gsv['latest']['panorama_counts']
    assert 'google_panos_age_stats' not in gsv['latest']
    assert gsv['latest']['is_baseline'] is True
    assert gsv['runs'][0]['unique_google_panos'] is None
    # No google contribution to the global gsv histograms
    assert summary['histogram_of_capture_dates']['gsv']['google_panos_yearly'] == {}

    strict_load(os.path.join(data_dir, 'cities.json.gz'))


def test_mapillary_run_json(data_dir):
    run_date = date(2026, 1, 15)
    csv_path = os.path.join(
        data_dir, 'duo--city_width_100_height_100_step_20_mapillary_2026-01-15.csv.gz')
    # 4 panos on 2 grid points (2 each) + 1 empty point: exercises the
    # rows-vs-grid-points distinction that only exists for Mapillary
    write_city_csv_gz(make_mapillary_city_df(
        [('m1', '2021-03-01'), ('m2', '2022-03-01'),
         ('m3', '2023-03-01'), ('m4', '2024-03-01')],
        run_date=run_date, panos_per_point=2), csv_path)
    df = load_city_csv_file(csv_path)
    json_path = generate_city_metadata_summary_as_json(
        csv_path, df, 'Duo', None, 'Testland', 100, 100, 20,
        force_recreate_file=True, run_date=run_date, provider='mapillary')
    data = strict_load(json_path)

    assert data['provider'] == 'mapillary'
    assert 'google_panos' not in data  # all rows are already provider panos
    assert data['all_panos']['duplicate_stats']['total_unique_panos'] == 4
    # search points count grid points, not pano rows
    assert data['search_grid']['total_search_points'] == 3
    assert data['data_file']['rows'] == 5
    # contributor breakdown replaces the single '© Google' photographer
    assert all(k.startswith('© Mapillary contributor')
               for k in data['all_panos']['top_10_photographers'])


def test_aggregate_v2_groups_runs_and_reports_change(conn, data_dir):
    city_id = db.register_city(
        conn, city_name='Duo', state_name=None, state_code=None,
        country_name='Testland', country_code=None,
        center_lat=44.0, center_lon=-121.0,
        grid_width_m=100, grid_height_m=100, step_m=20)

    for run_date, panos, csv_name in [
        (date(2026, 1, 15), [('p1', '2020-01-15')],
         f'{city_id}_width_100_height_100_step_20_2026-01-15.csv.gz'),
        (date(2026, 4, 15), [('p1', '2020-01-15'), ('p2', '2024-01-15')],
         f'{city_id}_width_100_height_100_step_20_2026-04-15.csv.gz'),
    ]:
        csv_path = _write_run(data_dir, panos, run_date, csv_name)
        df = load_city_csv_file(csv_path)
        json_path = generate_city_metadata_summary_as_json(
            csv_path, df, 'Duo', None, 'Testland', 100, 100, 20,
            force_recreate_file=True, run_date=run_date)
        run_id = db.register_run(conn, city_id=city_id, run_date=run_date,
                                 csv_filename=csv_name,
                                 json_filename=os.path.basename(json_path),
                                 unique_google_panos=len(panos))
    prev, latest = db.get_runs_for_city(conn, city_id)
    db.record_diff(conn, city_id=city_id, from_run_id=prev.run_id,
                   to_run_id=latest.run_id, grid_aligned=True, panos_added=1,
                   panos_removed=0, panos_persisted=1, capture_date_changed=0,
                   points_gained_coverage=1, points_lost_coverage=0,
                   coverage_delta_pct=33.3, detail_filename=None)

    summary = generate_aggregate_v2(conn, data_dir)

    assert summary['schema_version'] == 3
    assert summary['cities_count'] == 1
    rec = summary['cities'][0]
    assert rec['city_id'] == city_id
    assert rec['city']['name'] == 'Duo'
    gsv = rec['providers']['gsv']
    assert len(gsv['runs']) == 2
    assert gsv['latest']['run_date'] == '2026-04-15'
    assert 'unique_google_panos' in gsv['latest']['panorama_counts']
    assert 'google_panos_age_stats' in gsv['latest']
    assert gsv['change']['panos_added'] == 1
    assert list(summary['histogram_of_capture_dates']) == ['gsv']

    # The written aggregate must be strict-parseable
    strict_load(os.path.join(data_dir, 'cities.json.gz'))


def test_aggregate_v3_two_providers(conn, data_dir):
    city_id = db.register_city(
        conn, city_name='Both', state_name=None, state_code=None,
        country_name='Testland', country_code=None,
        center_lat=44.0, center_lon=-121.0,
        grid_width_m=100, grid_height_m=100, step_m=20)

    # One gsv run and two mapillary runs (mapillary latest has a diff)
    gsv_csv = f'{city_id}_width_100_height_100_step_20_2026-01-15.csv.gz'
    csv_path = _write_run(data_dir, [('g1', '2020-01-15')], date(2026, 1, 15), gsv_csv)
    df = load_city_csv_file(csv_path)
    json_path = generate_city_metadata_summary_as_json(
        csv_path, df, 'Both', None, 'Testland', 100, 100, 20,
        force_recreate_file=True, run_date=date(2026, 1, 15))
    db.register_run(conn, city_id=city_id, run_date=date(2026, 1, 15),
                    csv_filename=gsv_csv,
                    json_filename=os.path.basename(json_path),
                    unique_panos=1, unique_google_panos=1)

    m_runs = []
    for run_date, panos in [
        (date(2026, 1, 15), [('m1', '2021-05-01')]),
        (date(2026, 4, 15), [('m1', '2021-05-01'), ('m2', '2024-05-01')]),
    ]:
        name = (f'{city_id}_width_100_height_100_step_20_mapillary_'
                f'{run_date.isoformat()}.csv.gz')
        csv_path = os.path.join(data_dir, name)
        write_city_csv_gz(make_mapillary_city_df(panos, run_date=run_date), csv_path)
        df = load_city_csv_file(csv_path)
        json_path = generate_city_metadata_summary_as_json(
            csv_path, df, 'Both', None, 'Testland', 100, 100, 20,
            force_recreate_file=True, run_date=run_date, provider='mapillary')
        m_runs.append(db.register_run(
            conn, city_id=city_id, run_date=run_date, csv_filename=name,
            provider='mapillary', json_filename=os.path.basename(json_path),
            unique_panos=len(panos)))
    db.record_diff(conn, city_id=city_id, from_run_id=m_runs[0],
                   to_run_id=m_runs[1], grid_aligned=True, panos_added=1,
                   panos_removed=0, panos_persisted=1, capture_date_changed=0,
                   points_gained_coverage=1, points_lost_coverage=0,
                   coverage_delta_pct=33.3, detail_filename=None)

    summary = generate_aggregate_v2(conn, data_dir)
    rec = summary['cities'][0]

    assert set(rec['providers']) == {'gsv', 'mapillary'}
    assert rec['city']['name'] == 'Both'  # taken from the gsv run

    mly = rec['providers']['mapillary']
    assert len(mly['runs']) == 2
    assert mly['latest']['run_date'] == '2026-04-15'
    assert mly['latest']['panorama_counts'] == {'unique_panos': 2}
    assert 'google_panos_age_stats' not in mly['latest']
    assert mly['change']['panos_added'] == 1
    assert mly['runs'][0]['unique_google_panos'] is None
    # The gsv series is untouched by the mapillary runs
    assert rec['providers']['gsv']['change'] is None
    assert len(rec['providers']['gsv']['runs']) == 1

    # Per-provider global histograms; mapillary's google section stays empty
    hists = summary['histogram_of_capture_dates']
    assert set(hists) == {'gsv', 'mapillary'}
    assert hists['mapillary']['all_panos_yearly'] == {'2021': 1, '2024': 1} or \
        hists['mapillary']['all_panos_yearly'] == {2021: 1, 2024: 1}
    assert hists['mapillary']['google_panos_yearly'] == {}

    strict_load(os.path.join(data_dir, 'cities.json.gz'))

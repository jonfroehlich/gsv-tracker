"""Shared fixtures: temp data dir, catalog DB, and a synthetic city CSV factory."""

import gzip
import os
import sys
from datetime import date, datetime, timezone

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gsv_metadata_tracker import db  # noqa: E402

COLUMNS = ['query_lat', 'query_lon', 'query_timestamp', 'pano_lat', 'pano_lon',
           'pano_id', 'capture_date', 'copyright_info', 'status']


def make_city_df(panos, run_date=date(2026, 1, 15), grid_origin=(44.0, -121.0),
                 n_empty=1):
    """
    Build a synthetic run DataFrame.

    Args:
        panos: list of (pano_id, capture_date_str) — one OK grid point each
        run_date: embedded in query_timestamp
        grid_origin: (lat, lon) of the first grid point; points step by 0.001
        n_empty: trailing ZERO_RESULTS points

    Returns raw (string-typed) DataFrame, like a freshly written CSV.
    """
    ts = datetime(run_date.year, run_date.month, run_date.day,
                  12, 0, tzinfo=timezone.utc).isoformat()
    rows = []
    lat0, lon0 = grid_origin
    for i, (pano_id, capture) in enumerate(panos):
        rows.append((lat0 + i * 0.001, lon0, ts, lat0 + i * 0.001 + 0.0001,
                     lon0 + 0.0001, pano_id, capture, '© Google', 'OK'))
    for j in range(n_empty):
        rows.append((lat0 + (len(panos) + j) * 0.001, lon0, ts, None, None,
                     None, None, None, 'ZERO_RESULTS'))
    return pd.DataFrame(rows, columns=COLUMNS)


def write_city_csv_gz(df, path):
    """Write a synthetic df the way the downloader does (gzipped CSV)."""
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as f:
        df.to_csv(f, index=False)
    return path


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


@pytest.fixture
def conn(data_dir):
    connection = db.connect(os.path.join(data_dir, "gsv_tracker.db"))
    yield connection
    connection.close()


@pytest.fixture
def city_df_factory():
    return make_city_df

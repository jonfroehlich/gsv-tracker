"""
Run-to-run diff engine for temporal GSV tracking.

Compares two collection runs of the same city and reports what changed:

- Pano level (primary): which pano_ids were added, removed, or persisted,
  and which persisted panos had their capture_date change.
- Grid-point level (only when the two runs sampled the same grid): how many
  query points gained or lost coverage (OK <-> ZERO_RESULTS transitions).

Grid geometry is frozen in the cities catalog (db.py), so post-migration
runs of the same city always align; pairs involving a pre-migration
baseline may not (geocoder drift), in which case grid-point stats are None.
"""

import gzip
import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Rounding used to key grid points; matches the precision the query
# coordinates survive a CSV round-trip with.
_COORD_DECIMALS = 6


@dataclass
class RunDiff:
    """Summary (and detail rows) of changes between two runs of a city."""
    panos_added: int
    panos_removed: int
    panos_persisted: int
    capture_date_changed: int
    grid_aligned: bool
    points_gained_coverage: Optional[int]
    points_lost_coverage: Optional[int]
    coverage_delta_pct: Optional[float]
    # Long-form detail rows: change_type, pano_id, pano_lat, pano_lon,
    # old_capture_date, new_capture_date
    detail: pd.DataFrame = field(repr=False, default=None)

    @property
    def has_changes(self) -> bool:
        return (self.panos_added + self.panos_removed +
                self.capture_date_changed) > 0


def _unique_ok_panos(df: pd.DataFrame) -> pd.DataFrame:
    """OK rows deduplicated on pano_id, keeping the newest capture_date."""
    ok = df[df['status'] == 'OK'].copy()
    ok = ok.sort_values('capture_date', na_position='first')
    return ok.drop_duplicates(subset=['pano_id'], keep='last')


def _capture_date_str(value) -> Optional[str]:
    """capture_date as 'YYYY-MM-DD' or None (handles NaT and raw strings)."""
    if pd.isna(value):
        return None
    if isinstance(value, str):
        return value
    return pd.Timestamp(value).date().isoformat()


def _grid_keys(df: pd.DataFrame) -> pd.Index:
    return pd.MultiIndex.from_arrays([
        df['query_lat'].round(_COORD_DECIMALS),
        df['query_lon'].round(_COORD_DECIMALS),
    ])


def compute_run_diff(df_old: pd.DataFrame, df_new: pd.DataFrame) -> RunDiff:
    """
    Compare two runs of the same city.

    Args:
        df_old: DataFrame of the earlier run (load_city_csv_file format)
        df_new: DataFrame of the later run

    Returns:
        RunDiff with pano-level counts, grid-point coverage transitions
        (None when the grids don't align), and a detail DataFrame with one
        row per changed pano.
    """
    old_panos = _unique_ok_panos(df_old).set_index('pano_id')
    new_panos = _unique_ok_panos(df_new).set_index('pano_id')

    old_ids = set(old_panos.index)
    new_ids = set(new_panos.index)

    added_ids = sorted(new_ids - old_ids)
    removed_ids = sorted(old_ids - new_ids)
    persisted_ids = sorted(old_ids & new_ids)

    detail_rows = []
    for pano_id in added_ids:
        row = new_panos.loc[pano_id]
        detail_rows.append({
            'change_type': 'pano_added',
            'pano_id': pano_id,
            'pano_lat': row['pano_lat'],
            'pano_lon': row['pano_lon'],
            'old_capture_date': None,
            'new_capture_date': _capture_date_str(row['capture_date']),
        })
    for pano_id in removed_ids:
        row = old_panos.loc[pano_id]
        detail_rows.append({
            'change_type': 'pano_removed',
            'pano_id': pano_id,
            'pano_lat': row['pano_lat'],
            'pano_lon': row['pano_lon'],
            'old_capture_date': _capture_date_str(row['capture_date']),
            'new_capture_date': None,
        })

    capture_date_changed = 0
    for pano_id in persisted_ids:
        old_date = _capture_date_str(old_panos.loc[pano_id, 'capture_date'])
        new_date = _capture_date_str(new_panos.loc[pano_id, 'capture_date'])
        if old_date != new_date:
            capture_date_changed += 1
            row = new_panos.loc[pano_id]
            detail_rows.append({
                'change_type': 'capture_date_changed',
                'pano_id': pano_id,
                'pano_lat': row['pano_lat'],
                'pano_lon': row['pano_lon'],
                'old_capture_date': old_date,
                'new_capture_date': new_date,
            })

    detail = pd.DataFrame(
        detail_rows,
        columns=['change_type', 'pano_id', 'pano_lat', 'pano_lon',
                 'old_capture_date', 'new_capture_date'])

    # Grid-point coverage transitions, only when both runs sampled the
    # exact same grid points
    old_keys = _grid_keys(df_old)
    new_keys = _grid_keys(df_new)
    grid_aligned = (len(old_keys) == len(new_keys)
                    and set(old_keys) == set(new_keys))

    points_gained = points_lost = coverage_delta = None
    if grid_aligned:
        old_status = pd.Series(df_old['status'].values, index=old_keys)
        new_status = pd.Series(df_new['status'].values, index=new_keys)
        # Duplicated grid keys shouldn't happen; guard so align() can't explode
        old_status = old_status[~old_status.index.duplicated(keep='first')]
        new_status = new_status[~new_status.index.duplicated(keep='first')]
        new_status = new_status.reindex(old_status.index)

        old_ok = old_status == 'OK'
        new_ok = new_status == 'OK'
        points_gained = int((~old_ok & new_ok).sum())
        points_lost = int((old_ok & ~new_ok).sum())

        n = len(old_status)
        coverage_delta = float((new_ok.sum() - old_ok.sum()) / n * 100) if n else 0.0
    else:
        logger.warning(
            "Query grids do not align between runs "
            f"({len(set(old_keys))} vs {len(set(new_keys))} unique points); "
            "skipping grid-point coverage transitions")

    return RunDiff(
        panos_added=len(added_ids),
        panos_removed=len(removed_ids),
        panos_persisted=len(persisted_ids),
        capture_date_changed=capture_date_changed,
        grid_aligned=grid_aligned,
        points_gained_coverage=points_gained,
        points_lost_coverage=points_lost,
        coverage_delta_pct=coverage_delta,
        detail=detail,
    )


def generate_diff_filename(city_id: str, from_date: str, to_date: str) -> str:
    """Basename for a published diff detail file."""
    return f"{city_id}_diff_{from_date}_to_{to_date}.csv.gz"


def write_diff_detail(diff: RunDiff, output_path: str) -> None:
    """Write the diff's detail rows as a gzipped CSV."""
    with gzip.open(output_path, 'wt', encoding='utf-8', newline='') as f:
        diff.detail.to_csv(f, index=False)
    logger.info(f"Wrote diff detail ({len(diff.detail)} rows) to {output_path}")

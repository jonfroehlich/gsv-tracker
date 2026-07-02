# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

GSV Tracker analyzes Google Street View (GSV) coverage and temporal patterns in cities **over time**. It samples a geographic grid around a city center, queries the GSV Static API metadata endpoint per point, and produces immutable dated snapshots per city plus run-to-run change summaries (panos added/removed, capture-date changes, coverage deltas) and interactive map visualizations.

## Setup and common commands

```bash
source .venv/bin/activate          # standard venv, deps in requirements.txt
pip install -r requirements.txt
pytest                             # run the test suite (fast, no network)

# Collect one dated snapshot of a city (skipped if a run <80 days old exists)
python gsv_tracker.py "Seattle, WA"
python gsv_tracker.py "Seattle, WA" --force --run-date 2026-07-02
python gsv_tracker.py "Seattle, WA" --check-boundary   # preview search area only

# Batch + scheduler
python run_cities.py cities.txt --continue-on-error
python -m gsv_metadata_tracker.scheduler status
python -m gsv_metadata_tracker.scheduler run-due --dry-run

# One-time migration of legacy (undated) data files into the catalog
python scripts/migrate_to_db.py            # dry run; --execute to apply

# Publish data/ to the UW Makeability Lab web server (rsync over SSH)
./sync_data_to_server.sh --dry-run
```

Requires `GMAPS_API_KEY` (Street View Static API enabled) in `.env` or the environment; loaded by `gsv_metadata_tracker/config.py`. Scheduler config lives in `config/scheduler.toml` (stdlib `tomllib`, Python ≥3.11).

## Architecture

**Temporal model.** Every run of a city is an immutable dated file `{city_id}_width_W_height_H_step_S_YYYY-MM-DD.csv.gz` plus a sibling `.json.gz` summary (schema v2). The SQLite catalog `data/gsv_tracker.db` (`gsv_metadata_tracker/db.py`, stdlib sqlite3/WAL, no ORM) is the operational source of truth: `cities` (canonical `city_id` + **frozen grid geometry** — future runs never re-geocode, so grids align exactly and diffs are meaningful), `city_aliases` (legacy slugs like `albany--ny`), `runs`, `run_diffs`, `api_usage` (daily budget ledger), `schedule_state`. The DB is local-only, never rsynced.

**Pipeline per run** (`gsv_metadata_tracker/cli.py` is the policy layer):
1. `db.resolve_city()` — known cities reuse frozen geometry (zero geocoding); unknown cities geocode once via `geoutils.py` (rate-limited Nominatim) and register.
2. Skip policy: `--min-days-since-last-run` (default 80) unless `--force`.
3. `download_async.py` — aiohttp downloader; caller supplies the output path (no skip logic inside); resumes interrupted runs via a `.downloading` sibling file; returns `api_requests` for the budget ledger.
4. `analysis.calculate_run_stats()` + `db.register_run()`.
5. `diff.compute_run_diff()` vs the previous run → `run_diffs` row + published `{city_id}_diff_{FROM}_to_{TO}.csv.gz` detail file.
6. `json_summarizer.generate_city_metadata_summary_as_json()` — per-run JSON v2, ages pinned to `run_date` (deterministic); then `generate_aggregate_v2()` builds `cities.json.gz` from the DB (grouped by city: `latest` + slim `runs[]` + `change`).

**Filename parsing is a contract.** `gsv_metadata_tracker/naming.py` is the single source of truth; its regex accepts all three filename generations (legacy `_step_20`, buggy `_step_20.0`, dated). `sanitize_city_query_str` behavior must never change — canonical `city_id`s and all legacy file slugs depend on it (note: interior periods are preserved, e.g. `st.-louis`).

**Scheduler** (`gsv_metadata_tracker/scheduler.py`): designed as a systemd user timer on makelab1 (units + install docs in `deploy/`). `run-due` collects cities whose last success is ≥ cycle_days − grace_days old (stalest first), each as a `gsv_tracker.py` subprocess, stopping at the daily request budget; then regenerates the aggregate once and publishes. Stagger = `sha256(city_id) % cycle_days`.

**Web frontend (`www/`).** Static vanilla JS + Leaflet + Chart.js 4, no build step. `gsv-utils.js` has `adaptCityRecord()` which flattens v2 aggregate records for the UI; `index.js` is the overview map (popup shows change-since-last-run); `city.js` streams the run's csv.gz and has a snapshot `<select>` for run history. Data is fetched from `https://makeabilitylab.cs.washington.edu/public/gsv-tracker/data/`, populated by `sync_data_to_server.sh` (which publishes only `*.csv.gz`/`*.json.gz` — logs, the DB, and bare CSVs are excluded).

**Tests** (`tests/`, pytest): pure-logic tests for naming, db, diff, JSON v2, scheduler due/budget logic, and an end-to-end migration test with synthetic fixtures. No network, no API mocking.

## Notes

- `data/` contains thousands of files — avoid globbing/listing it wholesale.
- Legacy pre-2026 data files are undated; they're registered as `is_baseline=1` runs by the migration script and are never renamed (published URLs stay stable).
- The sync-vs-async duplicate download path was removed in v2 (`download.py`, `gsv_tracker_single.py`); v1.0.0 tag preserves the old architecture.
- Logs go to `logs/`, never `data/` (data/ is synced to a public web server).

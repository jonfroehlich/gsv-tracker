# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

GSV Tracker analyzes street-level imagery coverage and temporal patterns in cities **over time**, for two providers: Google Street View (GSV, the default) and Mapillary (360° panos only). It samples a geographic grid around a city center, queries each provider's metadata API, and produces immutable dated snapshots per (city, provider) plus run-to-run change summaries (panos added/removed, capture-date changes, coverage deltas) and interactive map visualizations.

## Setup and common commands

```bash
source .venv/bin/activate          # standard venv, deps in requirements.txt
pip install -r requirements.txt
pytest                             # run the test suite (fast, no network)

# Collect dated snapshots of a city — BOTH providers by default, same run
# date (per-provider skip if a run <80 days old exists)
python gsv_tracker.py "Seattle, WA"
python gsv_tracker.py "Seattle, WA" --provider mapillary   # restrict to one provider
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

Credentials in `.env`, loaded by `gsv_metadata_tracker/config.py` per provider: `GMAPS_API_KEY` (Street View Static API enabled) for gsv, `MAPILLARY_ACCESS_TOKEN` (free client token) for mapillary. The default `--provider both` requires both keys up-front (fail-fast so the series can't drift); a single-provider run needs only its own key. Scheduler config lives in `config/scheduler.toml` (stdlib `tomllib`, Python ≥3.11).

## Architecture

**Temporal model.** Every run of a city is an immutable dated file `{city_id}_width_W_height_H_step_S[_PROVIDER]_YYYY-MM-DD.csv.gz` plus a sibling `.json.gz` summary (schema v2; carries a `provider` field). **No provider token means gsv** — all pre-provider filenames and published URLs are unchanged. The SQLite catalog `data/gsv_tracker.db` (`gsv_metadata_tracker/db.py`, stdlib sqlite3/WAL, no ORM; schema v2, auto-migrated on connect) is the operational source of truth: `cities` (canonical `city_id` + **frozen grid geometry** — future runs never re-geocode, so grids align exactly and diffs are meaningful; geometry is shared by all providers), `city_aliases` (legacy slugs like `albany--ny`), `runs` (UNIQUE(city_id, provider, run_date)), `run_diffs`, `api_usage` (daily budget ledger, keyed by (date, provider)), `schedule_state` (keyed by (city, provider)). The DB is local-only, never rsynced.

**Provider model.** Each provider is an independent run series on the same frozen grid. GSV: one metadata request per grid point (nearest pano — a grid *sample*). Mapillary (`download_mapillary.py`): z14 vector tiles (~10–100 requests/city, `mapbox-vector-tile` dep), keeps **every** `is_pano` image assigned to its nearest grid point (a *census*), one CSV row per pano plus ZERO_RESULTS fill; bogus contributor timestamps become NO_DATE. Both write the identical 9-column CSV schema (`config.METADATA_DTYPES`), so coverage rates are cross-provider comparable but raw pano counts are census-vs-sample and are not. `runs.unique_google_panos` is NULL for non-gsv runs. Official-Google classification is an exact `© Google` match (`analysis.is_google_copyright`, shared by stats/JSON/vis and mirrored in `city.js`) — never substring, since photographer names can contain "Google".

**Pipeline per run** (`gsv_metadata_tracker/cli.py` is the policy layer; `--provider` threads through everything):
1. `db.resolve_city()` — known cities reuse frozen geometry (zero geocoding); unknown cities geocode once via `geoutils.py` (rate-limited Nominatim) and register, with the user's query slug saved as an alias so the same query never re-geocodes. `--check-boundary` uses the same resolution, so preview filenames and geometry match what a real run would produce.
2. Skip policy per (city, provider): `--min-days-since-last-run` (default 80) unless `--force`.
3. Downloader dispatch — `download_async.py` (gsv; resumes via a `.downloading` sibling) or `download_mapillary.py` (no resume — runs take seconds). Caller supplies the output path; both return `api_requests` for the per-provider budget ledger.
4. Guard: a run ≥95% REQUEST_DENIED/OVER_QUERY_LIMIT (`analysis.detect_systemic_failure`) is rejected before cataloging — csv renamed `*.rejected` (excluded from the publish glob), nonzero exit so the scheduler counts a failure. Otherwise `analysis.calculate_run_stats()` + `db.register_run()`.
5. `diff.compute_run_diff()` vs the previous run of the same provider → `run_diffs` row + published detail file (`{city_id}_diff_[PROVIDER_]{FROM}_to_{TO}.csv.gz`; gsv keeps the tokenless form).
6. `json_summarizer.generate_city_metadata_summary_as_json()` — per-run JSON v2, ages pinned to `run_date` (deterministic); gsv runs include the `google_panos` block, other providers only `all_panos`. Then `generate_aggregate_v2()` builds `cities.json.gz` (**schema v3**) from the DB: per city `{city_id, city, providers: {gsv: {latest, runs, change}, mapillary: {...}}}`, with per-provider global histograms.

**Filename parsing is a contract.** `gsv_metadata_tracker/naming.py` is the single source of truth; its regex accepts all filename generations (legacy `_step_20`, buggy `_step_20.0`, dated, provider-tagged). `sanitize_city_query_str` behavior must never change — canonical `city_id`s and all legacy file slugs depend on it (note: interior periods are preserved, e.g. `st.-louis`).

**Scheduler** (`gsv_metadata_tracker/scheduler.py`): designed as a systemd user timer on makelab1 (units + install docs in `deploy/`). `run-due` collects cities whose last success is ≥ cycle_days − grace_days old (stalest first); a due city runs all enabled providers back-to-back with the same run date (paired snapshots), each as a `gsv_tracker.py --provider X` subprocess within its own daily budget (`[providers.gsv]`/`[providers.mapillary]` in scheduler.toml; a legacy toml without `[providers]` runs gsv-only). Then regenerates the aggregate once and publishes. Stagger = `sha256(city_id) % cycle_days`, identical for all providers of a city.

**Web frontend (`www/`).** Static vanilla JS + Leaflet + Chart.js 4, no build step. `gsv-utils.js` has the `PROVIDERS` registry (labels, per-provider color-scale anchors — GSV 2007 vs Mapillary 2014 — viewer deep-links, attribution) and `adaptCityRecord(rec, provider)` which flattens v1/v2/v3 aggregate records and emits normalized `pano_count`/`pano_age_stats`/`capture_year_histogram` keys; `index.js` is the overview map with a GSV/Mapillary radio toggle (persisted as `?provider=`, re-renders without refetching); `city.js` streams the run's csv.gz (provider derived from the filename token; GSV rows filtered to official `© Google`, Mapillary rows all kept) and has a snapshot `<select>` filtered to the active provider's runs. Data is fetched from `https://makeabilitylab.cs.washington.edu/public/gsv-tracker/data/`, populated by `sync_data_to_server.sh` (which publishes only `*.csv.gz`/`*.json.gz` — logs, the DB, and bare CSVs are excluded). Mapillary attribution is required by their ToS and rendered in the Leaflet attribution control.

**Historical capture-date harvester (`download_gsv_history.py`, issue #2).** Separate, opt-in, and out-of-band from the run pipeline. A normal run records only the *current* capture date per grid point; this harvests the FULL official-Google capture history — every past drive-through and its month — which no documented Google API (free or paid) exposes. It comes instead from an **unpublished endpoint** (`GeoPhotoService.SingleImageSearch`, the backend behind the Maps-JS `getPanorama().time[]` array), queried directly with no API key. Because it is undocumented **there is no guarantee it keeps working**, and it is IP-identified rather than key-metered, so the harvester is deliberately gentle: low concurrency, per-request jitter, exponential backoff on throttle responses (429/403/503), a circuit breaker that aborts on a run of throttles (cf. `analysis.detect_systemic_failure`), and a resumable `.harvesting` checkpoint. It sweeps the city's frozen grid, keeps only panos that carry a date (a present date is the endpoint-native signal of official Google imagery — the analogue of the `© Google` filter), de-dups by pano_id, and writes a distinct dated artifact `{city_id}_..._gsv_history_YYYY-MM-DD.csv.gz` (its own `HISTORY_DTYPES` schema, NOT a run/`METADATA_DTYPES` file; `naming.parse_filename` rejects it, `parse_history_filename` parses it) plus a `history_harvests` catalog row (schema v3). History is near-static, so a city is harvested once and re-swept rarely. Run via `scripts/harvest_gsv_history.py "City"` (city must already be registered so its grid is frozen). Downstream JSON/diff/web-viz are intentionally deferred.

**Tests** (`tests/`, pytest): pure-logic tests for naming, db (incl. the v1→v2 migration against embedded v1 SQL), diff, JSON v2/aggregate v3, Mapillary tile math/decode/grid assignment (tiles built with `mapbox_vector_tile.encode`, end-to-end download served from memory), the GSV history harvester (response parsing, dated-only filter, cross-grid dedup, circuit breaker, resume — endpoint mocked), scheduler due/budget/provider-pairing logic, and an end-to-end migration test with synthetic fixtures. No network, no API mocking.

## Notes

- Architecture decisions are recorded in `docs/adr/`. Notably **ADR 0001: stay fully static, no backend** — the public site has zero server-side runtime by design; large/dense-city rendering (#77, #58) is fixed with static artifacts (grid-binned overview → PMTiles), never a server.
- `data/` contains thousands of files — avoid globbing/listing it wholesale.
- Legacy pre-2026 data files are undated; they're registered as `is_baseline=1` runs by the migration script and are never renamed (published URLs stay stable).
- The sync-vs-async duplicate download path was removed in v2 (`download.py`, `gsv_tracker_single.py`); v1.0.0 tag preserves the old architecture.
- Logs go to `logs/`, never `data/` (data/ is synced to a public web server).

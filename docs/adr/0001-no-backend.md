# ADR 0001: Keep Streetscape Tracker fully static (no real backend)

- **Status:** Accepted (2026-07-08)
- **Related issues:** #77 (dense-city rendering), #58 (city.html forced reflow), #69 (single-pano / 0-area viz crash)

## Context

Streetscape Tracker is a batch pipeline that produces immutable dated snapshots per
`(city, provider)` — `{city}_..._DATE.csv.gz` + sibling `.json.gz`, plus a single
`cities.json.gz` aggregate — served as static files from the UW CSE Apache web server
via `rsync` (`sync_data_to_server.sh`). The frontend (`www/`, vanilla JS + Leaflet +
Chart.js, no build step) fetches those files directly and decompresses/renders in the
browser. The SQLite catalog (`data/streetscape_tracker.db`) is the local operational source of
truth and is never published.

The question raised: should we stand up a "real backend" (a persistent API/DB service)?

## Decision

**No. Stay fully static.** We deliberately keep zero server-side runtime for the public
site.

The workload has none of the properties that justify a backend: it is read-only for end
users, append-only and batch-regenerated (data changes on a schedule, not per request),
and accessed one city at a time plus one small precomputed aggregate. This is the
textbook profile for static hosting.

v2 temporal tracking *reinforces* this rather than undermining it: comparing immutable,
dated snapshots is a batch computation — the pipeline's strength — and diffs/change
summaries are precomputed at generation time (`run_diffs`, published diff files,
aggregate `change` block). A backend's usual temporal edge (recompute comparisons on
demand) is wasted when every comparison is known the moment a run is generated.

Running a backend is *possible* (we operate servers for Project Sidewalk and BikeButler),
but it would add cross-team infra dependency, ops surface (Docker, patching, monitoring,
uptime), and loss of the current `git push` → webhook deploy agility — to buy capability
we do not currently need.

## Consequences

**The one real weakness is large/dense-city rendering** (e.g. Juneau 588 MB, Houston
399 MB, LA 279 MB *compressed*; symptomatic in #77 and #58). Every viable fix stays
static and lives in the pipeline + frontend, in increasing effort:

1. **Render stopgap** — cap rendered points / canvas render / "very large city" notice
   above a threshold in `city.js`.
2. **Grid-binned overview tier** — pipeline emits a decimated default file for big
   cities; frontend loads it by default. Must **grid-bin/aggregate**, not random-drop,
   so density and coverage gaps stay honest for a coverage tool.
3. **PMTiles for detail-on-zoom** — a single-file tile archive served over plain HTTP
   range requests (Apache supports byte ranges natively, no server). "Subsample +
   hi-def on zoom", done properly, *is* PMTiles.
4. **DuckDB-Wasm over Parquet** — only if ad-hoc cross-city querying is ever needed;
   real SQL entirely in the browser, still no backend.

Note that #69 is the opposite extreme — a single-pano / 0-area-bbox degenerate case,
unrelated to the giant-city problem — already guarded in the pipeline.

## Revisit triggers (when a backend would become the right call)

- Adding **writes**: user accounts, saved views, annotations, uploads.
- **Arbitrary ad-hoc queries** over the full dataset (~15 GB) we can't/won't
  pre-generate.
- **Storage growth** from retaining every full snapshot becoming impractical —
  PostGIS-style delta storage (dedupe unchanged panos across runs) is the one genuine
  backend advantage, and it is a storage-*efficiency* argument, not a capability one.
  Years away at the current ~1 run/city average.

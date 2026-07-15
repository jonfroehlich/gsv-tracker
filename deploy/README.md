# Deploying the Streetscape Tracker scheduler on makelab1

The scheduler runs as a **user-level systemd timer** on
`makelab1.cs.washington.edu` (a RHEL 9-family host): a oneshot service fires
nightly, collects the cities due that day (staggered quarterly cycle,
bounded by a daily API-request budget), diffs each against its previous
run, regenerates the aggregate JSON, and publishes `data/` to the public
web docroot. All state lives in `data/streetscape_tracker.db`, so crashes and
missed days self-heal.

## Where things live

makelab1 is the **compute** host; storage is NFS from other servers, so
this is deliberately split:

| What | Path | Notes |
|------|------|-------|
| Code + data + DB + logs + `.env` | `/projects/makeabilitylab/streetscape-tracker/` | On the lab fileserver (backed up, group `makelab`). **Not web-served.** Shared with other lab services. |
| Convenience symlink | `~/streetscape-tracker` → the path above | Lets the generic `%h/streetscape-tracker` systemd units and `.env` resolve. |
| Public web docroot | `/cse/web/research/makelab/public/streetscape-tracker/` | On a *different* host (the web-file server); served at `makeabilitylab.cs.washington.edu/public/streetscape-tracker/`. Holds only the flattened website + published `*.csv.gz`/`*.json.gz`. |

Because makelab1 mounts the docroot directly, **publishing is a local
rsync — no SSH to the docroot host** (`STREETSCAPE_PUBLISH_LOCAL=1`, set in the systemd unit).

## 1. One-time setup

```bash
ssh makelab1.cs.washington.edu

# Clone onto lab storage, and symlink it into home for the systemd units
git clone https://github.com/jonfroehlich/streetscape-tracker.git /projects/makeabilitylab/streetscape-tracker
ln -s /projects/makeabilitylab/streetscape-tracker ~/streetscape-tracker

cd ~/streetscape-tracker
python3.11 -m venv .venv          # 3.11+ for tomllib
# requirements.lock pins exact versions (uv pip compile --universal) so the
# deploy matches CI byte-for-byte; requirements.txt holds the loose floors.
.venv/bin/pip install -r requirements.lock

# API keys — copy your working .env up from the laptop (least error-prone):
#   (from the laptop)  scp .env makelab1.cs.washington.edu:/projects/makeabilitylab/streetscape-tracker/.env
chmod 600 .env                    # seal the keys; the parent dir is group-readable
```

## 2. Move the data + catalog up

The SQLite catalog `streetscape_tracker.db` lives **inside** `data/`, so this
one rsync carries both the ~15 GB of snapshots *and* the catalog itself.
Copying the live catalog is the point: it is the only place the frozen grid
geometry, city aliases, and boundary re-registrations (issue #91) exist —
none of that is reconstructable from the CSV/JSON files alone, and the DB is
never in git. This is a *different* rsync from `sync_data_to_server.sh`, which
publishes to the public docroot and deliberately **excludes** the DB.

First, make sure the catalog is checkpointed and no session has it open, so
rsync copies a consistent file rather than a stale one with pending writes in
the `-wal` sidecar:

```bash
# (on the laptop) flush the WAL into the main .db, then confirm nothing holds it
sqlite3 data/streetscape_tracker.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

Then copy `data/` up (includes the `.db`; the `-wal`/`-shm` sidecars will be
empty after the checkpoint):

```bash
rsync -azh --progress data/ makelab1.cs.washington.edu:/projects/makeabilitylab/streetscape-tracker/data/
```

That's it — makelab1 now has your exact catalog. The migration script below is
a **safety-net no-op** in this path: with the catalog already populated it just
re-confirms every file is registered and reports zero changes. Run it only to
verify (or if you ever seed makelab1 from data files *without* copying the DB —
note that route loses the #91 boundary re-registrations, which live solely in
the catalog):

```bash
cd ~/streetscape-tracker
.venv/bin/python scripts/migrate_to_db.py            # dry run — expect 0 new registrations
.venv/bin/python scripts/migrate_to_db.py --execute  # optional; safe to skip if dry run is clean
```

## 3. Sanity-check the config

The production config `config/scheduler.makelab1.toml` is checked in and
already points at the paths above, enables local publish, and enables email
alerts. Confirm mail delivers, then preview a run:

```bash
echo "streetscape-tracker mail test $(date)" | mail -s "streetscape test" you@example.edu
# NB: --config is global and must come BEFORE the subcommand.
.venv/bin/python -m streetscape_metadata_tracker.scheduler --config config/scheduler.makelab1.toml status
.venv/bin/python -m streetscape_metadata_tracker.scheduler --config config/scheduler.makelab1.toml run-due --dry-run
```

Start conservative for the first few nights — set `max_cities_per_day = 2`
in the TOML, watch, then raise. (See **First full backfill** below.)

## 4. Clean up the public docroot + deploy the website

The docroot currently holds a legacy full-repo checkout (`.git/`, `scripts/`,
`config/`, `.venv/`, `*.py`, …) — none of which belongs on a web server.
`deploy_makelab1.sh` publishes the site **flattened** (so it serves at
`.../public/streetscape-tracker/` with no `/www/` in the URL) and its `--delete`
sweeps that legacy junk, while **protecting** `data/`, `poster/`, `cities/`,
and `data-huge/`. Preview first:

```bash
cd ~/streetscape-tracker
./deploy_makelab1.sh --dry-run     # shows exactly what is added/deleted
./deploy_makelab1.sh               # pulls latest code, then prompts before applying
```

### One-time: rename the public data path (GSV Tracker → Streetscape Tracker)

The public docroot moved from `/public/gsv-tracker/` to
`/public/streetscape-tracker/` (repo/product rename). The frontend
(`STREETSCAPE_DATA_BASE_URL`) and `sync_data_to_server.sh` now target the new
path. On the docroot host, do this **once** so existing published `*.csv.gz`
links (which already point at the old path) don't 404:

```bash
cd /cse/web/research/makelab/public
mv gsv-tracker streetscape-tracker          # move existing data + site in place
ln -s streetscape-tracker gsv-tracker       # old URLs keep resolving via the symlink
```

Run this whenever you push new frontend/backend code. The nightly **data**
publish is separate and automatic (step 5).

## 5. Install the systemd units (user-level, no root)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/streetscape-tracker.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now streetscape-tracker.timer
loginctl enable-linger $USER       # user services must survive logout
```

The service ships with resource caps (`MemoryMax=8G`, `CPUQuota=400%`,
`Nice=10`) so nightly collection can't starve the other lab services that
share the box and the storage array. If `enable-linger` is disallowed by policy,
ask CSE IT to enable lingering for your account.

## 6. Operate

```bash
systemctl --user list-timers streetscape-tracker.timer      # next scheduled run
journalctl --user -u streetscape-tracker.service -f          # live logs
systemctl --user start streetscape-tracker.service           # trigger a run now
.venv/bin/python -m streetscape_metadata_tracker.scheduler --config config/scheduler.makelab1.toml status
```

Rotating file logs also go to `logs/streetscape_scheduler.log`, and a rolling
catalog backup to `logs/streetscape_tracker.db.backup`.

### Watching resource use (alongside other co-tenants)

```bash
systemd-cgtop                                        # live CPU/mem per cgroup — streetscape vs co-tenants
systemctl --user show streetscape-tracker.service -p MemoryPeak -p CPUUsageNSec
```

Validate the caps after the first live night: if `MemoryPeak` approaches
`MemoryMax`, raise it (or lower `batch_size`/`connection_limit` in the TOML).
Data lives on NFS, so IO is network (not block-device) — CPU/memory caps and
`Nice` are the real levers; `IOWeight` would not govern it.

### Failure alerts (email)

Enabled in `config/scheduler.makelab1.toml` (`transport = "mail"`, which
delivers on makelab1 with no relay setup). Test end-to-end without waiting for
a failure:

```bash
.venv/bin/python -m streetscape_metadata_tracker.scheduler --config config/scheduler.makelab1.toml notify-failure
```

**Optional systemd safety net** — for an email even when the process dies
before it can send its own (OOM, kill): install the notify unit and uncomment
`OnFailure=` in `streetscape-tracker.service`:

```bash
cp deploy/systemd/streetscape-tracker-notify@.service ~/.config/systemd/user/
# then uncomment OnFailure= in streetscape-tracker.service and daemon-reload
```

It fires on *any* nonzero exit (run-due returns nonzero on any failed city),
so it can duplicate the scheduler's own threshold email — enable only if you
want belt-and-suspenders coverage.

### First full backfill

Post-#91, every city needs a fresh run on the new frozen geometry, so the
first cycle is a big one-time burst (not steady state). Once a few nights look
healthy, raise `max_cities_per_day` (and optionally trigger extra daytime
batches with `systemctl --user start streetscape-tracker.service`) to catch up, then
drop back to the steady ~quarterly cadence (`max_cities_per_day = 20` keeps
~1,144 cities on the 90-day cycle with headroom).

### Disabling a city

```bash
sqlite3 data/streetscape_tracker.db "UPDATE cities SET enabled = 0 WHERE city_id = '...'"
```

A city that fails `max_consecutive_failures` nights in a row is skipped
automatically until you reset it:

```bash
sqlite3 data/streetscape_tracker.db "UPDATE schedule_state SET consecutive_failures = 0 WHERE city_id = '...'"
```

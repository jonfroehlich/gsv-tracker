# Deploying the GSV Tracker scheduler on makelab1

The scheduler runs as a **user-level systemd timer** on
`makelab1.cs.washington.edu` (Rocky Linux 9): a oneshot service fires
nightly, collects the cities due that day (staggered quarterly cycle,
bounded by a daily API-request budget), diffs each against its previous
run, regenerates the aggregate JSON, and publishes `data/` to the public
web docroot. All state lives in `data/gsv_tracker.db`, so crashes and
missed days self-heal.

## Where things live

makelab1 is the **compute** host; storage is NFS from other servers, so
this is deliberately split:

| What | Path | Notes |
|------|------|-------|
| Code + data + DB + logs + `.env` | `/projects/makeabilitylab/gsv-tracker/` | On the lab fileserver **makelab2** (42 TB, backed up, group `makelab`). **Not web-served.** Colocated with Project Sidewalk. |
| Convenience symlink | `~/gsv-tracker` → the path above | Lets the generic `%h/gsv-tracker` systemd units and `.env` resolve. |
| Public web docroot | `/cse/web/research/makelab/public/gsv-tracker/` | On a *different* server (`new-rumble`); served at `makeabilitylab.cs.washington.edu/public/gsv-tracker/`. Holds only the flattened website + published `*.csv.gz`/`*.json.gz`. |

Because makelab1 mounts the docroot directly, **publishing is a local
rsync — no SSH to recycle** (`GSV_PUBLISH_LOCAL=1`, set in the systemd unit).

## 1. One-time setup

```bash
ssh makelab1.cs.washington.edu

# Clone onto lab storage, and symlink it into home for the systemd units
git clone https://github.com/jonfroehlich/gsv-tracker.git /projects/makeabilitylab/gsv-tracker
ln -s /projects/makeabilitylab/gsv-tracker ~/gsv-tracker

cd ~/gsv-tracker
python3.11 -m venv .venv          # 3.11+ for tomllib
.venv/bin/pip install -r requirements.txt

# API keys — copy your working .env up from the laptop (least error-prone):
#   (from the laptop)  scp .env makelab1.cs.washington.edu:/projects/makeabilitylab/gsv-tracker/.env
chmod 600 .env                    # seal the keys; the parent dir is group-readable
```

## 2. Move the data + catalog up

From the machine that currently holds `data/` (laptop), ~15 GB:

```bash
rsync -azh --progress data/ makelab1.cs.washington.edu:/projects/makeabilitylab/gsv-tracker/data/
```

Then register the existing files as baseline runs (dry-run first, review, execute):

```bash
cd ~/gsv-tracker
.venv/bin/python scripts/migrate_to_db.py            # dry run
.venv/bin/python scripts/migrate_to_db.py --execute
```

## 3. Sanity-check the config

The production config `config/scheduler.makelab1.toml` is checked in and
already points at the paths above, enables local publish, and enables email
alerts. Confirm mail delivers, then preview a run:

```bash
echo "gsv-tracker mail test $(date)" | mail -s "gsv test" jonf@cs.uw.edu
# NB: --config is global and must come BEFORE the subcommand.
.venv/bin/python -m gsv_metadata_tracker.scheduler --config config/scheduler.makelab1.toml status
.venv/bin/python -m gsv_metadata_tracker.scheduler --config config/scheduler.makelab1.toml run-due --dry-run
```

Start conservative for the first few nights — set `max_cities_per_day = 2`
in the TOML, watch, then raise. (See **First full backfill** below.)

## 4. Clean up the public docroot + deploy the website

The docroot currently holds a legacy full-repo checkout (`.git/`, `scripts/`,
`config/`, `.venv/`, `*.py`, …) — none of which belongs on a web server.
`deploy_makelab1.sh` publishes the site **flattened** (so it serves at
`.../public/gsv-tracker/` with no `/www/` in the URL) and its `--delete`
sweeps that legacy junk, while **protecting** `data/`, `poster/`, `cities/`,
and `data-huge/`. Preview first:

```bash
cd ~/gsv-tracker
./deploy_makelab1.sh --dry-run     # shows exactly what is added/deleted
./deploy_makelab1.sh               # pulls latest code, then prompts before applying
```

Run this whenever you push new frontend/backend code. The nightly **data**
publish is separate and automatic (step 5).

## 5. Install the systemd units (user-level, no root)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/gsv-tracker.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gsv-tracker.timer
loginctl enable-linger $USER       # user services must survive logout
```

The service ships with resource caps (`MemoryMax=8G`, `CPUQuota=400%`,
`Nice=10`) so nightly collection can't starve Project Sidewalk, which shares
the box and the makelab2 array. If `enable-linger` is disallowed by policy,
ask CSE IT to enable lingering for your account.

## 6. Operate

```bash
systemctl --user list-timers gsv-tracker.timer      # next scheduled run
journalctl --user -u gsv-tracker.service -f          # live logs
systemctl --user start gsv-tracker.service           # trigger a run now
.venv/bin/python -m gsv_metadata_tracker.scheduler --config config/scheduler.makelab1.toml status
```

Rotating file logs also go to `logs/gsv_scheduler.log`, and a rolling
catalog backup to `logs/gsv_tracker.db.backup`.

### Watching resource use (alongside Project Sidewalk)

```bash
systemd-cgtop                                        # live CPU/mem per cgroup — gsv vs sidewalk
systemctl --user show gsv-tracker.service -p MemoryPeak -p CPUUsageNSec
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
.venv/bin/python -m gsv_metadata_tracker.scheduler --config config/scheduler.makelab1.toml notify-failure
```

**Optional systemd safety net** — for an email even when the process dies
before it can send its own (OOM, kill): install the notify unit and uncomment
`OnFailure=` in `gsv-tracker.service`:

```bash
cp deploy/systemd/gsv-tracker-notify@.service ~/.config/systemd/user/
# then uncomment OnFailure= in gsv-tracker.service and daemon-reload
```

It fires on *any* nonzero exit (run-due returns nonzero on any failed city),
so it can duplicate the scheduler's own threshold email — enable only if you
want belt-and-suspenders coverage.

### First full backfill

Post-#91, every city needs a fresh run on the new frozen geometry, so the
first cycle is a big one-time burst (not steady state). Once a few nights look
healthy, raise `max_cities_per_day` (and optionally trigger extra daytime
batches with `systemctl --user start gsv-tracker.service`) to catch up, then
drop back to the steady ~quarterly cadence (`max_cities_per_day = 20` keeps
~1,144 cities on the 90-day cycle with headroom).

### Disabling a city

```bash
sqlite3 data/gsv_tracker.db "UPDATE cities SET enabled = 0 WHERE city_id = '...'"
```

A city that fails `max_consecutive_failures` nights in a row is skipped
automatically until you reset it:

```bash
sqlite3 data/gsv_tracker.db "UPDATE schedule_state SET consecutive_failures = 0 WHERE city_id = '...'"
```

# Deploying the GSV Tracker scheduler on makelab1

The scheduler runs as a **user-level systemd timer** on
`makelab1.cs.washington.edu` (Rocky Linux 9): a oneshot service fires
nightly, collects the cities due that day (staggered quarterly cycle,
bounded by a daily API-request budget), diffs each against its previous
run, regenerates the aggregate JSON, and rsyncs `data/` to the public web
server. All state lives in `data/gsv_tracker.db`, so crashes and missed
days self-heal.

## 1. One-time setup

```bash
ssh makelab1.cs.washington.edu

# Clone and set up the environment (needs Python >= 3.11 for tomllib)
git clone https://github.com/jonfroehlich/gsv-tracker.git ~/gsv-tracker
cd ~/gsv-tracker
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# API keys (same file the CLI uses) — the scheduler collects both
# providers by default, so both are required
echo 'GMAPS_API_KEY=YOUR_KEY_HERE' > .env
echo 'MAPILLARY_ACCESS_TOKEN=YOUR_TOKEN_HERE' >> .env
chmod 600 .env
```

## 2. Move the data + catalog to makelab1

From the machine that currently holds `data/` (laptop):

```bash
rsync -azh --progress data/ makelab1.cs.washington.edu:gsv-tracker/data/
```

Then, on makelab1, register the existing files as baseline runs (dry-run
first, review the report, then execute):

```bash
cd ~/gsv-tracker
.venv/bin/python scripts/migrate_to_db.py            # dry run
.venv/bin/python scripts/migrate_to_db.py --execute
```

## 3. Configure

Edit `config/scheduler.toml`: uncomment and set the `[paths]` entries to
absolute paths, review `daily_request_budget` / `max_cities_per_day`, and
set `[publish] enabled = true` once you've confirmed SSH key auth from
makelab1 to the web host (`recycle.cs.washington.edu`) works:

```bash
ssh recycle.cs.washington.edu true   # should succeed without a password
```

Sanity-check before enabling the timer:

```bash
.venv/bin/python -m gsv_metadata_tracker.scheduler status
.venv/bin/python -m gsv_metadata_tracker.scheduler run-due --dry-run
```

## 4. Install the systemd units (user-level, no root needed)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/gsv-tracker.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gsv-tracker.timer

# User services must survive logout:
loginctl enable-linger $USER
```

If `enable-linger` is disallowed by policy, ask CSE IT to enable lingering
for your account (or to install the units as a system service).

## 5. Operate

```bash
systemctl --user list-timers gsv-tracker.timer      # next scheduled run
journalctl --user -u gsv-tracker.service -f          # live logs
.venv/bin/python -m gsv_metadata_tracker.scheduler status
systemctl --user start gsv-tracker.service           # trigger a run now
```

Rotating file logs are also written to `logs/gsv_scheduler.log`, and a
rolling catalog backup to `logs/gsv_tracker.db.backup`.

### First week

Start conservatively: set `max_cities_per_day = 2` and a low
`daily_request_budget` (e.g. `30000`) in the TOML, watch a few nights of
journal output and the public site, then raise to production values
(defaults in the example TOML).

### Disabling a city

```bash
sqlite3 data/gsv_tracker.db "UPDATE cities SET enabled = 0 WHERE city_id = '...'"
```

A city that fails `max_consecutive_failures` nights in a row is skipped
automatically until you reset it:

```bash
sqlite3 data/gsv_tracker.db "UPDATE schedule_state SET consecutive_failures = 0 WHERE city_id = '...'"
```

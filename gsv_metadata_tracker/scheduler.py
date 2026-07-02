"""
Staggered collection scheduler for GSV Tracker.

Designed to run as a daily systemd timer (oneshot): each invocation of
`run-due` collects the cities that are due today, within a configurable
daily API-request budget, then regenerates the aggregate JSON and
(optionally) publishes to the web server. All state lives in the SQLite
catalog, so the process is crash-safe and a missed day self-heals (due
selection is ordered stalest-first).

Usage:
    python -m gsv_metadata_tracker.scheduler status   [--config PATH]
    python -m gsv_metadata_tracker.scheduler assign   [--config PATH]
    python -m gsv_metadata_tracker.scheduler run-due  [--config PATH] [--dry-run] [--limit N]

Config: TOML (see config/scheduler.toml). Requires Python 3.11+ (tomllib).
"""

import argparse
import logging
import logging.handlers
import os
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from tabulate import tabulate

from . import db
from .json_summarizer import generate_aggregate_v2

logger = logging.getLogger("gsv_scheduler")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "scheduler.toml"


@dataclass
class SchedulerConfig:
    # [schedule]
    cycle_days: int = 90
    grace_days: int = 7
    daily_request_budget: int = 250_000
    max_cities_per_day: int = 20
    max_consecutive_failures: int = 5
    city_timeout_minutes: int = 180
    # [download]
    batch_size: int = 100
    connection_limit: int = 50
    request_timeout_s: float = 30.0
    sleep_between_cities_s: int = 60
    # [paths]
    data_dir: str = str(_PROJECT_ROOT / "data")
    db_path: str = ""
    log_dir: str = str(_PROJECT_ROOT / "logs")
    # [publish]
    publish_enabled: bool = False
    publish_script: str = str(_PROJECT_ROOT / "sync_data_to_server.sh")

    def __post_init__(self):
        if not self.db_path:
            self.db_path = db.get_default_db_path(self.data_dir)


def load_scheduler_config(path: Optional[str] = None) -> SchedulerConfig:
    """Load scheduler config from TOML; missing file yields defaults."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        logger.warning(f"Config {config_path} not found; using defaults")
        return SchedulerConfig()

    with open(config_path, 'rb') as f:
        raw = tomllib.load(f)

    sched = raw.get('schedule', {})
    dl = raw.get('download', {})
    paths = raw.get('paths', {})
    pub = raw.get('publish', {})
    return SchedulerConfig(
        cycle_days=sched.get('cycle_days', 90),
        grace_days=sched.get('grace_days', 7),
        daily_request_budget=sched.get('daily_request_budget', 250_000),
        max_cities_per_day=sched.get('max_cities_per_day', 20),
        max_consecutive_failures=sched.get('max_consecutive_failures', 5),
        city_timeout_minutes=sched.get('city_timeout_minutes', 180),
        batch_size=dl.get('batch_size', 100),
        connection_limit=dl.get('connection_limit', 50),
        request_timeout_s=dl.get('request_timeout_s', 30.0),
        sleep_between_cities_s=dl.get('sleep_between_cities_s', 60),
        data_dir=paths.get('data_dir', str(_PROJECT_ROOT / "data")),
        db_path=paths.get('db_path', ''),
        log_dir=paths.get('log_dir', str(_PROJECT_ROOT / "logs")),
        publish_enabled=pub.get('enabled', False),
        publish_script=pub.get('publish_script', str(_PROJECT_ROOT / "sync_data_to_server.sh")),
    )


def estimate_requests(city: db.CityRow) -> int:
    """Estimated API requests for one run: number of grid points."""
    return ((city.grid_width_m // city.step_m + 1)
            * (city.grid_height_m // city.step_m + 1))


def setup_logging(cfg: SchedulerConfig, verbose: bool = False) -> None:
    os.makedirs(cfg.log_dir, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout)]
    file_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(cfg.log_dir, "gsv_scheduler.log"),
        when='midnight', backupCount=30)
    handlers.append(file_handler)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers)


def cmd_status(cfg: SchedulerConfig) -> int:
    """Print a per-city schedule table plus today's budget usage."""
    conn = db.connect(cfg.db_path)
    today = datetime.now(timezone.utc).date()

    rows = conn.execute(
        """SELECT c.city_id, c.enabled, s.day_of_cycle, s.last_success_at,
                  s.consecutive_failures, s.last_error,
                  (SELECT MAX(run_date) FROM runs r WHERE r.city_id = c.city_id) AS last_run
           FROM cities c LEFT JOIN schedule_state s ON s.city_id = c.city_id
           ORDER BY s.last_success_at ASC NULLS FIRST, c.city_id""").fetchall()

    due = db.get_due_cities(conn, today=today, cycle_days=cfg.cycle_days,
                            grace_days=cfg.grace_days,
                            max_consecutive_failures=cfg.max_consecutive_failures)
    due_ids = {c.city_id for c in due}

    table = [[r['city_id'],
              'yes' if r['enabled'] else 'no',
              r['day_of_cycle'],
              r['last_run'] or '—',
              (r['last_success_at'] or '—')[:10],
              r['consecutive_failures'] or 0,
              'DUE' if r['city_id'] in due_ids else '']
             for r in rows]
    print(tabulate(table,
                   headers=['city', 'enabled', 'cycle day', 'last run',
                            'last success', 'failures', ''],
                   tablefmt='simple'))
    used = db.get_api_usage(conn, today)
    print(f"\n{len(rows)} cities; {len(due)} due today ({today}).")
    print(f"API budget today: {used:,} / {cfg.daily_request_budget:,} requests used.")
    return 0


def cmd_assign(cfg: SchedulerConfig) -> int:
    """(Re)compute the day-of-cycle stagger assignment for all cities."""
    conn = db.connect(cfg.db_path)
    n = db.assign_schedule(conn, cfg.cycle_days)
    print(f"Assigned day_of_cycle for {n} enabled cities over a "
          f"{cfg.cycle_days}-day cycle (~{n / max(cfg.cycle_days, 1):.1f} cities/day).")
    return 0


def _run_one_city(cfg: SchedulerConfig, city: db.CityRow, today: date) -> bool:
    """Collect one city via a gsv_tracker.py subprocess. Returns success."""
    cmd = [
        sys.executable, str(_PROJECT_ROOT / "gsv_tracker.py"),
        city.display_name,
        "--run-date", today.isoformat(),
        "--download-dir", cfg.data_dir,
        "--db-path", cfg.db_path,
        "--batch-size", str(cfg.batch_size),
        "--connection-limit", str(cfg.connection_limit),
        "--timeout", str(cfg.request_timeout_s),
        "--no-visual",
        "--no-publish-json",
        "--log-level", "INFO",
    ]
    logger.info(f"Collecting {city.city_id} "
                f"(~{estimate_requests(city):,} requests estimated)")
    logger.debug(f"Command: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, timeout=cfg.city_timeout_minutes * 60, cwd=str(_PROJECT_ROOT))
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"{city.city_id}: timed out after {cfg.city_timeout_minutes} minutes")
        return False


def cmd_run_due(cfg: SchedulerConfig, dry_run: bool = False,
                limit: Optional[int] = None) -> int:
    """Collect all cities due today, within budget, then publish."""
    conn = db.connect(cfg.db_path)
    today = datetime.now(timezone.utc).date()

    # Ensure new cities have stagger assignments
    db.assign_schedule(conn, cfg.cycle_days)

    due = db.get_due_cities(conn, today=today, cycle_days=cfg.cycle_days,
                            grace_days=cfg.grace_days,
                            max_consecutive_failures=cfg.max_consecutive_failures)
    if limit is not None:
        due = due[:limit]
    day_cap = min(len(due), cfg.max_cities_per_day)

    logger.info(f"{len(due)} cities due on {today}; "
                f"processing up to {day_cap} within a budget of "
                f"{cfg.daily_request_budget:,} requests")

    if dry_run:
        used = db.get_api_usage(conn, today)
        budget_left = cfg.daily_request_budget - used
        print(f"DRY RUN — would process (budget remaining {budget_left:,}):")
        for city in due[:day_cap]:
            est = estimate_requests(city)
            fits = "ok" if est <= budget_left else "OVER BUDGET (deferred)"
            print(f"  {city.city_id:60s} ~{est:>9,} req  {fits}")
            budget_left -= est if est <= budget_left else 0
        return 0

    processed = succeeded = skipped_budget = 0
    for city in due:
        if processed >= cfg.max_cities_per_day:
            logger.info("Daily city cap reached; stopping for today")
            break

        est = estimate_requests(city)
        if est > cfg.daily_request_budget:
            # This city can NEVER fit the daily budget — skipping (not
            # breaking) so it can't starve every smaller city behind it
            # in the stalest-first queue. Needs a manual run or a config
            # change; surfaced loudly so it doesn't rot silently.
            logger.warning(
                f"{city.city_id}: ~{est:,} estimated requests exceeds the "
                f"entire daily budget ({cfg.daily_request_budget:,}). "
                f"Skipping — run manually with gsv_tracker.py --force, "
                f"raise daily_request_budget, or set enabled=0.")
            skipped_budget += 1
            continue

        used = db.get_api_usage(conn, today)
        if used + est > cfg.daily_request_budget:
            # Doesn't fit in what's LEFT today — try the next (smaller)
            # city rather than ending the day; this one rolls to tomorrow
            # when the budget is fresh.
            logger.info(
                f"{city.city_id} (~{est:,} req) doesn't fit remaining "
                f"budget ({cfg.daily_request_budget - used:,} left); skipping.")
            skipped_budget += 1
            continue

        ok = _run_one_city(cfg, city, today)
        processed += 1
        if ok:
            succeeded += 1
            db.record_attempt(conn, city.city_id, success=True)
        else:
            db.record_attempt(conn, city.city_id, success=False,
                              error=f"subprocess failed on {today}")
            logger.error(f"{city.city_id}: collection failed")

        if processed < len(due):
            time.sleep(cfg.sleep_between_cities_s)

    logger.info(f"Done: {succeeded}/{processed} cities succeeded"
                + (f"; {skipped_budget} deferred for budget" if skipped_budget else ""))

    # Regenerate the aggregate once for the whole batch
    if succeeded > 0:
        logger.info("Regenerating aggregate cities.json.gz")
        generate_aggregate_v2(conn, cfg.data_dir)

    # Nightly catalog backup (keep one rolling copy alongside the logs)
    backup_path = os.path.join(cfg.log_dir, "gsv_tracker.db.backup")
    try:
        import sqlite3
        with sqlite3.connect(backup_path) as backup_conn:
            conn.backup(backup_conn)
        logger.info(f"Catalog backed up to {backup_path}")
    except Exception as e:
        logger.error(f"Catalog backup failed: {e}")

    if cfg.publish_enabled and succeeded > 0:
        logger.info(f"Publishing via {cfg.publish_script}")
        result = subprocess.run(["bash", cfg.publish_script], cwd=str(_PROJECT_ROOT))
        if result.returncode != 0:
            logger.error("Publish script failed")
            return 1

    return 0 if succeeded == processed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m gsv_metadata_tracker.scheduler",
        description="Staggered GSV collection scheduler")
    parser.add_argument('--config', default=None,
                        help=f'Path to scheduler TOML (default: {DEFAULT_CONFIG_PATH})')
    parser.add_argument('--verbose', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('status', help='Show per-city schedule and budget status')
    sub.add_parser('assign', help='(Re)compute stagger assignments')
    p_run = sub.add_parser('run-due', help="Collect today's due cities")
    p_run.add_argument('--dry-run', action='store_true',
                       help='Print what would run; no downloads')
    p_run.add_argument('--limit', type=int, default=None,
                       help='Process at most N cities (testing)')

    args = parser.parse_args()
    cfg = load_scheduler_config(args.config)
    setup_logging(cfg, verbose=args.verbose)

    if args.command == 'status':
        return cmd_status(cfg)
    if args.command == 'assign':
        return cmd_assign(cfg)
    if args.command == 'run-due':
        return cmd_run_due(cfg, dry_run=args.dry_run, limit=args.limit)
    return 2


if __name__ == '__main__':
    sys.exit(main())

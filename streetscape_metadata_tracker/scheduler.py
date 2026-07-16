"""
Staggered collection scheduler for Streetscape Tracker.

Designed to run as a daily systemd timer (oneshot): each invocation of
`run-due` collects the cities that are due today, within a configurable
daily API-request budget, then regenerates the aggregate JSON and
(optionally) publishes to the web server. All state lives in the SQLite
catalog, so the process is crash-safe and a missed day self-heals (due
selection is ordered stalest-first).

Usage (--config accepted on either side of the subcommand):
    python -m streetscape_metadata_tracker.scheduler [--config PATH] status
    python -m streetscape_metadata_tracker.scheduler [--config PATH] assign
    python -m streetscape_metadata_tracker.scheduler [--config PATH] run-due [--dry-run] [--limit N]
    python -m streetscape_metadata_tracker.scheduler [--config PATH] regenerate-aggregate [--publish]

Config: TOML (see config/scheduler.toml). Requires Python 3.11+ (tomllib).
"""

import argparse
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import time
import tomllib
import traceback
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from tabulate import tabulate

from . import db
from .alerting import AlertConfig, send_alert, should_alert
from .download_common import redact_credentials
from .download_mapillary import estimate_tile_count
from .json_summarizer import generate_aggregate_v2
from .naming import KNOWN_PROVIDERS

logger = logging.getLogger("streetscape_scheduler")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "scheduler.toml"


@dataclass
class ProviderConfig:
    """Per-provider scheduling settings ([providers.NAME] in the TOML)."""

    enabled: bool = True
    daily_request_budget: int = 250_000  # gsv: metadata requests; mapillary: tiles


@dataclass
class SchedulerConfig:
    # [schedule]
    cycle_days: int = 90
    grace_days: int = 7
    daily_request_budget: int = 10_000_000  # legacy gsv budget ([providers] overrides)
    max_cities_per_day: int = 20
    max_consecutive_failures: int = 5
    city_timeout_minutes: int = 180
    # [download]
    batch_size: int = 100
    connection_limit: int = 50
    request_timeout_s: float = 30.0
    sleep_between_cities_s: int = 60
    # Client-side gsv pacing; 80% of the API's default 30k/min quota. Scale
    # with the project's granted quota. 0 disables.
    max_requests_per_minute: int = 24_000
    # [paths]
    data_dir: str = str(_PROJECT_ROOT / "data")
    db_path: str = ""
    log_dir: str = str(_PROJECT_ROOT / "logs")
    # [publish]
    publish_enabled: bool = False
    publish_script: str = str(_PROJECT_ROOT / "sync_data_to_server.sh")
    # [providers.*] — when None (no section in the TOML), falls back to
    # gsv-only with the legacy [schedule].daily_request_budget
    providers: dict[str, ProviderConfig] | None = None
    # [alerts] — operator email on unhealthy runs (off by default)
    alerts: AlertConfig = field(default_factory=AlertConfig)

    def __post_init__(self):
        if not self.db_path:
            self.db_path = db.get_default_db_path(self.data_dir)
        if self.providers is None:
            self.providers = {"gsv": ProviderConfig(daily_request_budget=self.daily_request_budget)}

    def enabled_providers(self) -> list[str]:
        """Enabled provider names, gsv first (the expensive series leads)."""
        return sorted(
            (p for p, pc in self.providers.items() if pc.enabled), key=lambda p: p != "gsv"
        )


def load_scheduler_config(path: str | None = None) -> SchedulerConfig:
    """Load scheduler config from TOML; missing file yields defaults."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        logger.warning(f"Config {config_path} not found; using defaults")
        return SchedulerConfig()

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    sched = raw.get("schedule", {})
    dl = raw.get("download", {})
    paths = raw.get("paths", {})
    pub = raw.get("publish", {})
    al = raw.get("alerts", {})

    providers = None
    if "providers" in raw:
        providers = {}
        for name, p in raw["providers"].items():
            if name not in KNOWN_PROVIDERS:
                logger.warning(
                    f"Ignoring unknown provider [providers.{name}] "
                    f"(known: {', '.join(KNOWN_PROVIDERS)})"
                )
                continue
            providers[name] = ProviderConfig(
                enabled=p.get("enabled", True),
                daily_request_budget=p.get("daily_request_budget", 250_000),
            )

    return SchedulerConfig(
        cycle_days=sched.get("cycle_days", 90),
        grace_days=sched.get("grace_days", 7),
        daily_request_budget=sched.get("daily_request_budget", 10_000_000),
        max_cities_per_day=sched.get("max_cities_per_day", 20),
        max_consecutive_failures=sched.get("max_consecutive_failures", 5),
        city_timeout_minutes=sched.get("city_timeout_minutes", 180),
        batch_size=dl.get("batch_size", 100),
        connection_limit=dl.get("connection_limit", 50),
        request_timeout_s=dl.get("request_timeout_s", 30.0),
        sleep_between_cities_s=dl.get("sleep_between_cities_s", 60),
        max_requests_per_minute=dl.get("max_requests_per_minute", 24_000),
        data_dir=paths.get("data_dir", str(_PROJECT_ROOT / "data")),
        db_path=paths.get("db_path", ""),
        log_dir=paths.get("log_dir", str(_PROJECT_ROOT / "logs")),
        publish_enabled=pub.get("enabled", False),
        publish_script=pub.get("publish_script", str(_PROJECT_ROOT / "sync_data_to_server.sh")),
        providers=providers,
        alerts=AlertConfig(
            enabled=al.get("enabled", False),
            recipient=al.get("recipient", ""),
            transport=al.get("transport", "mail"),
            command=al.get("command", ""),
            failure_threshold=al.get("failure_threshold", 1),
            subject_prefix=al.get("subject_prefix", "[streetscape-tracker]"),
        ),
    )


def estimate_requests(city: db.CityRow, provider: str = "gsv") -> int:
    """
    Estimated API requests for one run: grid points for GSV (one metadata
    request per point), z14 tile count for Mapillary (bulk metadata).
    """
    if provider == "mapillary":
        return estimate_tile_count(
            city.center_lat, city.center_lon, city.grid_width_m, city.grid_height_m, city.step_m
        )
    return (city.grid_width_m // city.step_m + 1) * (city.grid_height_m // city.step_m + 1)


def setup_logging(cfg: SchedulerConfig, verbose: bool = False) -> None:
    os.makedirs(cfg.log_dir, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout)]
    file_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(cfg.log_dir, "streetscape_scheduler.log"), when="midnight", backupCount=30
    )
    handlers.append(file_handler)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def _recent_log_tail(cfg: SchedulerConfig, n: int = 40) -> str:
    """
    Last n lines of the scheduler log, for pasting into an alert email.

    Scrubbed with redact_credentials as the last line of defense: anything
    that slipped an API key/token into a log line must not travel further
    in a cleartext email.
    """
    log_path = os.path.join(cfg.log_dir, "streetscape_scheduler.log")
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            return redact_credentials("".join(f.readlines()[-n:])) or "(log empty)"
    except OSError as e:
        return f"(could not read {log_path}: {e})"


def _publish(cfg: SchedulerConfig, context: str) -> int:
    """
    Run the publish script (rsync data/ to the web server), returning its exit
    code and emailing the operator on failure. ``context`` (e.g. the run-due
    summary) is prepended to the alert body so the email is self-explanatory.
    """
    logger.info(f"Publishing via {cfg.publish_script}")
    result = subprocess.run(["bash", cfg.publish_script], cwd=str(_PROJECT_ROOT))
    if result.returncode != 0:
        logger.error("Publish script failed")
        send_alert(
            cfg.alerts,
            f"publish script FAILED on {socket.gethostname()}",
            f"{context}\n\nPublish step exited nonzero.\n\nRecent log:\n{_recent_log_tail(cfg)}",
        )
    return result.returncode


def cmd_notify_failure(cfg: SchedulerConfig) -> int:
    """
    Email that the scheduled run failed. Intended for a systemd
    ``OnFailure=`` hook, which fires when the unit exits nonzero (a crash, or
    — since run-due returns nonzero on any failed city — a failed collection
    the in-run threshold alert may have already covered). Best-effort.
    """
    host = socket.gethostname()
    body = (
        "streetscape-tracker's scheduled run exited nonzero (systemd OnFailure).\n\n"
        "Recent log:\n" + _recent_log_tail(cfg, 60)
    )
    sent = send_alert(cfg.alerts, f"scheduled run FAILED on {host}", body)
    # 0 when we alerted or alerting is intentionally off; 1 only if a send was
    # attempted and failed, so the notify unit's own status is meaningful.
    return 0 if sent or not cfg.alerts.enabled else 1


def cmd_status(cfg: SchedulerConfig) -> int:
    """Print a per-(city, provider) schedule table plus today's budgets."""
    conn = db.connect(cfg.db_path)
    today = datetime.now(UTC).date()
    providers = cfg.enabled_providers()

    rows = conn.execute(
        """SELECT c.city_id, c.enabled, s.provider, s.day_of_cycle,
                  s.last_success_at, s.consecutive_failures, s.last_error,
                  (SELECT MAX(run_date) FROM runs r
                   WHERE r.city_id = c.city_id
                     AND r.provider = COALESCE(s.provider, 'gsv')) AS last_run
           FROM cities c LEFT JOIN schedule_state s ON s.city_id = c.city_id
           ORDER BY s.last_success_at ASC NULLS FIRST, c.city_id,
                    s.provider"""
    ).fetchall()

    due_pairs = set()
    due_counts = {}
    for provider in providers:
        due = db.get_due_cities(
            conn,
            today=today,
            cycle_days=cfg.cycle_days,
            grace_days=cfg.grace_days,
            max_consecutive_failures=cfg.max_consecutive_failures,
            provider=provider,
        )
        due_counts[provider] = len(due)
        due_pairs.update((c.city_id, provider) for c in due)

    table = [
        [
            r["city_id"],
            r["provider"] or "—",
            "yes" if r["enabled"] else "no",
            r["day_of_cycle"],
            r["last_run"] or "—",
            (r["last_success_at"] or "—")[:10],
            r["consecutive_failures"] or 0,
            "DUE" if (r["city_id"], r["provider"] or "gsv") in due_pairs else "",
        ]
        for r in rows
        if r["provider"] is None or r["provider"] in providers
    ]
    print(
        tabulate(
            table,
            headers=[
                "city",
                "provider",
                "enabled",
                "cycle day",
                "last run",
                "last success",
                "failures",
                "",
            ],
            tablefmt="simple",
        )
    )

    n_cities = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    due_str = ", ".join(f"{due_counts[p]} {p}" for p in providers)
    print(f"\n{n_cities} cities; due today ({today}): {due_str}.")
    for provider in providers:
        used = db.get_api_usage(conn, today, provider)
        budget = cfg.providers[provider].daily_request_budget
        print(f"{provider} budget today: {used:,} / {budget:,} requests used.")
    return 0


def cmd_assign(cfg: SchedulerConfig) -> int:
    """(Re)compute the day-of-cycle stagger assignment for all cities."""
    conn = db.connect(cfg.db_path)
    providers = tuple(cfg.enabled_providers())
    n = db.assign_schedule(conn, cfg.cycle_days, providers=providers)
    print(
        f"Assigned day_of_cycle for {n} enabled cities x "
        f"{len(providers)} provider(s) over a {cfg.cycle_days}-day cycle "
        f"(~{n / max(cfg.cycle_days, 1):.1f} cities/day)."
    )
    return 0


def cmd_regenerate(cfg: SchedulerConfig, publish: bool = False) -> int:
    """
    Rebuild the aggregate ``cities.json.gz`` from the catalog without collecting
    anything, then optionally publish. Useful after a code change to the
    aggregate schema, a manual/back-filled run, or to refresh stale published
    data — a clean one-liner instead of an inline Python snippet.
    """
    conn = db.connect(cfg.db_path)
    logger.info("Regenerating aggregate cities.json.gz")
    agg = generate_aggregate_v2(conn, cfg.data_dir)
    print(f"Regenerated {cfg.data_dir}/cities.json.gz ({agg['cities_count']} cities).")

    if publish:
        # An explicit --publish overrides [publish].enabled: the operator is
        # asking for it directly on the command line.
        if _publish(cfg, "regenerate-aggregate (manual)") != 0:
            return 1
        print("Published to the web server.")
    return 0


def _run_one_city(
    cfg: SchedulerConfig, city: db.CityRow, today: date, provider: str = "gsv"
) -> bool:
    """Collect one (city, provider) via a streetscape_tracker.py subprocess."""
    cmd = [
        sys.executable,
        str(_PROJECT_ROOT / "streetscape_tracker.py"),
        "--provider",
        provider,
        "--run-date",
        today.isoformat(),
        "--download-dir",
        cfg.data_dir,
        "--db-path",
        cfg.db_path,
        "--batch-size",
        str(cfg.batch_size),
        "--connection-limit",
        str(cfg.connection_limit),
        "--max-requests-per-minute",
        str(cfg.max_requests_per_minute),
        "--timeout",
        str(cfg.request_timeout_s),
        # The scheduler already decided this city is due (cycle − grace),
        # so disable the CLI's own skip window. Otherwise any config with
        # cycle_days − grace_days ≤ the CLI default (80) makes every run
        # "succeed" as a skip — stamping last_success_at while never
        # collecting anything, forever, with green logs.
        "--min-days-since-last-run",
        "0",
        "--no-visual",
        "--no-publish-json",
        "--log-level",
        "INFO",
        # '--' so a display name can never be parsed as a flag
        "--",
        city.display_name,
    ]
    logger.info(
        f"Collecting {city.city_id} [{provider}] "
        f"(~{estimate_requests(city, provider):,} requests estimated)"
    )
    logger.debug(f"Command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, timeout=cfg.city_timeout_minutes * 60, cwd=str(_PROJECT_ROOT))
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(
            f"{city.city_id} [{provider}]: timed out after {cfg.city_timeout_minutes} minutes"
        )
        return False


def _collect_due(conn, cfg: SchedulerConfig, today: date):
    """
    Due work for today: an ordered city list (stalest-first, gsv's order
    leading since it's the expensive series) and, per city, which enabled
    providers are due. Providers pair on the same cycle day by design, so
    most cities are due for all providers at once; they only diverge after
    per-provider failures or when a provider was enabled later.
    """
    due_by_provider = {
        provider: db.get_due_cities(
            conn,
            today=today,
            cycle_days=cfg.cycle_days,
            grace_days=cfg.grace_days,
            max_consecutive_failures=cfg.max_consecutive_failures,
            provider=provider,
        )
        for provider in cfg.enabled_providers()
    }
    ordered, seen = [], set()
    providers_for_city = {}
    for provider, due in due_by_provider.items():
        for city in due:
            if city.city_id not in seen:
                seen.add(city.city_id)
                ordered.append(city)
            providers_for_city.setdefault(city.city_id, []).append(provider)
    return ordered, providers_for_city


def cmd_run_due(
    cfg: SchedulerConfig,
    dry_run: bool = False,
    limit: int | None = None,
    today: date | None = None,
) -> int:
    """
    Collect all cities due today, within per-provider budgets, publish.

    ``today`` is injectable so tests can pin a date (a wall-clock read here
    can cross UTC midnight mid-test and flake); production callers omit it.
    """
    conn = db.connect(cfg.db_path)
    if today is None:
        today = datetime.now(UTC).date()
    providers = cfg.enabled_providers()

    # Ensure new cities (and newly enabled providers) have stagger assignments
    db.assign_schedule(conn, cfg.cycle_days, providers=tuple(providers))

    due, providers_for_city = _collect_due(conn, cfg, today)
    if limit is not None:
        due = due[:limit]
    day_cap = min(len(due), cfg.max_cities_per_day)

    budget_str = ", ".join(f"{cfg.providers[p].daily_request_budget:,} {p}" for p in providers)
    logger.info(
        f"{len(due)} cities due on {today}; "
        f"processing up to {day_cap} within daily budgets of "
        f"{budget_str} requests"
    )

    if dry_run:
        budget_left = {
            p: cfg.providers[p].daily_request_budget - db.get_api_usage(conn, today, p)
            for p in providers
        }
        left_str = ", ".join(f"{budget_left[p]:,} {p}" for p in providers)
        print(f"DRY RUN — would process (budget remaining {left_str}):")
        for city in due[:day_cap]:
            for provider in providers_for_city[city.city_id]:
                est = estimate_requests(city, provider)
                fits = "ok" if est <= budget_left[provider] else "OVER BUDGET (deferred)"
                print(f"  {city.city_id:60s} {provider:10s} ~{est:>9,} req  {fits}")
                budget_left[provider] -= est if est <= budget_left[provider] else 0
        return 0

    processed = succeeded = attempted = skipped_budget = 0
    for city in due:
        if processed >= cfg.max_cities_per_day:
            logger.info("Daily city cap reached; stopping for today")
            break

        ran_any = False
        for provider in providers_for_city[city.city_id]:
            budget = cfg.providers[provider].daily_request_budget
            est = estimate_requests(city, provider)
            if est > budget:
                # This city can NEVER fit the daily budget — skipping (not
                # breaking) so it can't starve every smaller city behind it
                # in the stalest-first queue. Needs a manual run or a config
                # change; surfaced loudly so it doesn't rot silently.
                logger.warning(
                    f"{city.city_id} [{provider}]: ~{est:,} estimated requests "
                    f"exceeds the entire daily budget ({budget:,}). "
                    f"Skipping — run manually with streetscape_tracker.py --force, "
                    f"raise daily_request_budget, or set enabled=0."
                )
                skipped_budget += 1
                continue

            used = db.get_api_usage(conn, today, provider)
            if used + est > budget:
                # Doesn't fit in what's LEFT today — try the next (smaller)
                # city rather than ending the day; this one rolls to tomorrow
                # when the budget is fresh.
                logger.info(
                    f"{city.city_id} [{provider}] (~{est:,} req) doesn't fit "
                    f"remaining budget ({budget - used:,} left); skipping."
                )
                skipped_budget += 1
                continue

            ok = _run_one_city(cfg, city, today, provider)
            ran_any = True
            attempted += 1
            if ok:
                succeeded += 1
                db.record_attempt(conn, city.city_id, success=True, provider=provider)
            else:
                db.record_attempt(
                    conn,
                    city.city_id,
                    success=False,
                    error=f"subprocess failed on {today}",
                    provider=provider,
                )
                logger.error(f"{city.city_id} [{provider}]: collection failed")

        if ran_any:
            processed += 1
            if processed < len(due):
                time.sleep(cfg.sleep_between_cities_s)

    summary = (
        f"run-due {today}: {succeeded}/{attempted} runs succeeded across "
        f"{processed} cities"
        + (f"; {skipped_budget} deferred for budget" if skipped_budget else "")
    )
    logger.info("Done: " + summary)

    # Regenerate the aggregate once for the whole batch
    if succeeded > 0:
        logger.info("Regenerating aggregate cities.json.gz")
        generate_aggregate_v2(conn, cfg.data_dir)

    # Nightly catalog backup (keep one rolling copy alongside the logs)
    backup_path = os.path.join(cfg.log_dir, "streetscape_tracker.db.backup")
    try:
        import sqlite3

        with sqlite3.connect(backup_path) as backup_conn:
            conn.backup(backup_conn)
        logger.info(f"Catalog backed up to {backup_path}")
    except Exception as e:
        logger.error(f"Catalog backup failed: {e}")

    if cfg.publish_enabled and succeeded > 0:
        if _publish(cfg, summary) != 0:
            return 1

    # Operator email when the batch finished unhealthy (threshold-controlled so
    # an occasional single flaky city doesn't page every night). No-op unless
    # [alerts] enabled.
    failures = attempted - succeeded
    if should_alert(failures, cfg.alerts.failure_threshold):
        send_alert(
            cfg.alerts,
            f"{failures} failed collection(s) on {socket.gethostname()}",
            f"{summary}\n\nRecent log:\n{_recent_log_tail(cfg)}",
        )

    return 0 if succeeded == attempted else 1


def _add_global_flags(p: argparse.ArgumentParser) -> None:
    """Add --config/--verbose to a parser.

    Applied to BOTH the top-level parser and every subparser so the flags are
    accepted on either side of the subcommand (``--config X run-due`` and
    ``run-due --config X`` both work — systemd/docs historically wrote it after).
    ``SUPPRESS`` defaults mean an unused copy never clobbers the value parsed at
    the other position.
    """
    p.add_argument(
        "--config",
        default=argparse.SUPPRESS,
        help=f"Path to scheduler TOML (default: {DEFAULT_CONFIG_PATH})",
    )
    p.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m streetscape_metadata_tracker.scheduler",
        description="Staggered GSV collection scheduler",
    )
    _add_global_flags(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    _add_global_flags(sub.add_parser("status", help="Show per-city schedule and budget status"))
    _add_global_flags(sub.add_parser("assign", help="(Re)compute stagger assignments"))
    p_regen = sub.add_parser(
        "regenerate-aggregate",
        help="Rebuild cities.json.gz from the catalog (no collection)",
    )
    _add_global_flags(p_regen)
    p_regen.add_argument(
        "--publish", action="store_true", help="Also rsync data/ to the web server afterward"
    )
    p_run = sub.add_parser("run-due", help="Collect today's due cities")
    _add_global_flags(p_run)
    p_run.add_argument("--dry-run", action="store_true", help="Print what would run; no downloads")
    p_run.add_argument("--limit", type=int, default=None, help="Process at most N cities (testing)")
    _add_global_flags(
        sub.add_parser(
            "notify-failure", help="Email the recent log (for a systemd OnFailure= hook)"
        )
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    # getattr fallbacks: SUPPRESS means the attr is absent unless the flag was given.
    cfg = load_scheduler_config(getattr(args, "config", None))
    setup_logging(cfg, verbose=getattr(args, "verbose", False))

    if args.command == "status":
        return cmd_status(cfg)
    if args.command == "assign":
        return cmd_assign(cfg)
    if args.command == "regenerate-aggregate":
        return cmd_regenerate(cfg, publish=args.publish)
    if args.command == "notify-failure":
        return cmd_notify_failure(cfg)
    if args.command == "run-due":
        try:
            return cmd_run_due(cfg, dry_run=args.dry_run, limit=args.limit)
        except Exception:
            # A crash (not just a failed city) — email the traceback before the
            # process dies, so a silent nightly failure can't go unnoticed.
            send_alert(
                cfg.alerts,
                f"run-due CRASHED on {socket.gethostname()}",
                f"Uncaught exception in run-due:\n\n{traceback.format_exc()}",
            )
            raise
    return 2


if __name__ == "__main__":
    sys.exit(main())

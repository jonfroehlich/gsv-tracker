#!/usr/bin/env bash
#
# deploy_makelab1.sh
#
# On-demand CODE + WEBSITE deploy for the makelab1 install. Run this after you
# push new frontend or backend code; the nightly *data* publish is separate and
# automatic (the scheduler runs sync_data_to_server.sh --local after each batch).
#
# What it does, from the private checkout it lives in:
#   1. git pull --ff-only              (fetch the latest code)
#   2. pip install (only if requirements.txt changed in the pull)
#   3. rsync www/ -> the public docroot, FLATTENED (so the site serves at
#      .../public/gsv-tracker/ with no /www/ in the URL), excluding dev tooling
#      (node_modules, eslint, tests, package files) and PROTECTING the docroot's
#      data/, poster/, cities/, data-huge/ from deletion.
#
# The first run also cleans a legacy full-repo checkout out of the docroot:
# --delete removes everything in the docroot that isn't a published site file or
# a protected data dir (old .git/, scripts/, config/, *.py, etc.).
#
# Safe by default: previews with --dry-run semantics and prompts before applying
# unless --yes is given. Makes ZERO provider API calls.
#
# Usage:
#   ./deploy_makelab1.sh                 # pull + preview + confirm + deploy site
#   ./deploy_makelab1.sh --dry-run       # show what would change, touch nothing
#   ./deploy_makelab1.sh --yes           # skip the confirmation prompt
#   ./deploy_makelab1.sh --skip-pull     # just re-publish the site (no git pull)
#
# Environment overrides:
#   GSV_DOCROOT   public docroot (default: /cse/web/research/makelab/public/gsv-tracker)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WWW_DIR="${REPO_DIR}/www"
DOCROOT="${GSV_DOCROOT:-/cse/web/research/makelab/public/gsv-tracker}"

DRY_RUN=""
ASSUME_YES=""
SKIP_PULL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-n) DRY_RUN="--dry-run"; shift ;;
    --yes|-y)     ASSUME_YES="1"; shift ;;
    --skip-pull)  SKIP_PULL="1"; shift ;;
    --help|-h)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Error: unknown option: $1 (try --help)"; exit 1 ;;
  esac
done

# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────
if [[ ! -d "$WWW_DIR" ]]; then
  echo "Error: www/ not found at $WWW_DIR (run from the gsv-tracker checkout)."
  exit 1
fi
if [[ ! -d "$DOCROOT" ]]; then
  echo "Error: docroot not found: $DOCROOT"
  echo "Set GSV_DOCROOT or create it first."
  exit 1
fi
command -v rsync >/dev/null || { echo "Error: rsync not installed."; exit 1; }

echo "═══════════════════════════════════════════"
echo " GSV Tracker: code + website deploy"
echo "═══════════════════════════════════════════"
echo "  Repo:    $REPO_DIR"
echo "  Site:    $WWW_DIR/  ->  $DOCROOT/  (flattened)"
[[ -n "$DRY_RUN" ]] && echo "  Mode:    DRY RUN"
echo ""

# ──────────────────────────────────────────────
# 1. Pull latest code (+ deps if requirements changed)
# ──────────────────────────────────────────────
if [[ -z "$SKIP_PULL" && -z "$DRY_RUN" ]]; then
  echo "→ git pull --ff-only"
  before="$(git -C "$REPO_DIR" rev-parse HEAD)"
  git -C "$REPO_DIR" pull --ff-only
  after="$(git -C "$REPO_DIR" rev-parse HEAD)"
  if [[ "$before" != "$after" ]] && \
     git -C "$REPO_DIR" diff --name-only "$before" "$after" | grep -qx 'requirements.txt'; then
    echo "→ requirements.txt changed — updating venv"
    "${REPO_DIR}/.venv/bin/pip" install -q -r "${REPO_DIR}/requirements.txt"
  fi
  echo ""
elif [[ -n "$SKIP_PULL" ]]; then
  echo "→ skipping git pull (--skip-pull)"
  echo ""
fi

# ──────────────────────────────────────────────
# 2. Publish the website (flattened into the docroot)
# ──────────────────────────────────────────────
# --delete keeps the docroot clean (and sweeps out any legacy full-repo files),
# but the anchored --exclude entries below are PROTECTED from deletion: rsync
# never removes an excluded path on the receiving side. That is what shields the
# 15 GB data/ (and the other static asset dirs) from --delete.
#
# The dev-tooling excludes keep node_modules/, tests, and package/lint files off
# the public web server.
RSYNC_ARGS=(
  -rlptvh --delete
  --chmod=D2755,F644
  # protect docroot content this script does not manage:
  --exclude='/data/'
  --exclude='/poster/'
  --exclude='/cities/'
  --exclude='/data-huge/'
  # NOTE: a legacy docroot/www/ subdir (from the old symlink layout) is
  # intentionally NOT excluded, so --delete sweeps it during the flatten.
  # keep dev tooling out of the published site:
  --exclude='node_modules/'
  --exclude='__tests__/'
  --exclude='eslint.config.js'
  --exclude='package.json'
  --exclude='package-lock.json'
  --exclude='.gitignore'
  --exclude='.git/'
)

if [[ -n "$DRY_RUN" ]]; then
  echo "→ Preview of website changes (no files touched):"
  rsync "${RSYNC_ARGS[@]}" --dry-run "$WWW_DIR/" "$DOCROOT/"
  echo ""
  echo "DRY RUN complete. Re-run without --dry-run to apply."
  exit 0
fi

# Real run: preview deletions first, then confirm (unless --yes).
echo "→ Preview (what the deploy will change):"
rsync "${RSYNC_ARGS[@]}" --dry-run "$WWW_DIR/" "$DOCROOT/" | sed 's/^/    /'
echo ""
if [[ -z "$ASSUME_YES" ]]; then
  read -r -p "Apply these changes to $DOCROOT ? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

rsync "${RSYNC_ARGS[@]}" "$WWW_DIR/" "$DOCROOT/"

echo ""
echo "Site deployed to: https://makeabilitylab.cs.washington.edu/public/gsv-tracker/"

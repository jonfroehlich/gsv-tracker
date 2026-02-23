#!/usr/bin/env bash
#
# sync_data_to_server.sh
#
# Syncs the local data/ directory to the UW CSE makeabilitylab web server
# using rsync over SSH for efficient incremental transfers.
#
# Remote path:  /cse/web/research/makelab/public/gsv-tracker/data
# Public URL:   https://makeabilitylab.cs.washington.edu/public/gsv-tracker/data/
#
# Usage:
#   ./sync_data_to_server.sh                  # sync all data
#   ./sync_data_to_server.sh --dry-run        # preview what would be transferred
#   ./sync_data_to_server.sh --file <file>    # sync a single file (relative to data/)
#   ./sync_data_to_server.sh --verbose        # show detailed transfer info
#   ./sync_data_to_server.sh --delete         # remove remote files not in local data/
#
# Prerequisites:
#   - SSH access to the remote host (key-based auth recommended)
#   - rsync installed locally and on the server. Requires rsync 3.1.0+ for --chmod support
#
# Platform notes:
#   - macOS/Linux: works out of the box
#   - Windows: use WSL, Git Bash, or install rsync via winget/scoop
#     (native PowerShell does not support rsync)

set -euo pipefail

# ──────────────────────────────────────────────
# Configuration (override via environment)
# ──────────────────────────────────────────────
REMOTE_USER="${GSV_REMOTE_USER:-jonf}"
REMOTE_HOST="${GSV_REMOTE_HOST:-recycle.cs.washington.edu}"
REMOTE_DATA_DIR="${GSV_REMOTE_DATA_DIR:-/cse/web/research/makelab/public/gsv-tracker/data}"

# Resolve local data/ relative to this script's location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_DATA_DIR="${SCRIPT_DIR}/data"

# Files to exclude from sync (temp/intermediate files)
EXCLUDE_PATTERNS=(
  "*.lock"
  "*.downloading"
  "*.backup"
  "*.html"
)

# ──────────────────────────────────────────────
# Parse arguments
# ──────────────────────────────────────────────
DRY_RUN=""
SINGLE_FILE=""
VERBOSE=""
DELETE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-n)
      DRY_RUN="--dry-run"
      shift
      ;;
    --file|-f)
      SINGLE_FILE="$2"
      shift 2
      ;;
    --verbose|-v)
      VERBOSE="--verbose"
      shift
      ;;
    --delete)
      DELETE="--delete"
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [--dry-run] [--file <path>] [--verbose] [--delete]"
      echo ""
      echo "Syncs local data/ to the UW makeabilitylab server."
      echo ""
      echo "Options:"
      echo "  --dry-run, -n    Preview changes without transferring"
      echo "  --file, -f       Sync a single file (path relative to data/)"
      echo "  --verbose, -v    Show detailed transfer info"
      echo "  --delete         Remove remote files not present locally"
      echo "  --help, -h       Show this help message"
      echo ""
      echo "Environment overrides:"
      echo "  GSV_REMOTE_USER  SSH username (default: jonf)"
      echo "  GSV_REMOTE_HOST  SSH host (default: recycle.cs.washington.edu)"
      echo "  GSV_REMOTE_DATA_DIR  Remote path (default: /cse/web/research/makelab/public/gsv-tracker/data)"
      exit 0
      ;;
    *)
      echo "Error: Unknown option: $1"
      echo "Run '$0 --help' for usage."
      exit 1
      ;;
  esac
done

# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────
if [[ ! -d "$LOCAL_DATA_DIR" ]]; then
  echo "Error: Local data directory not found: $LOCAL_DATA_DIR"
  echo "Make sure you run this script from the gsv-tracker repo root."
  exit 1
fi

if ! command -v rsync &> /dev/null; then
  echo "Error: rsync is not installed."
  echo "  macOS:   rsync should be pre-installed"
  echo "  Ubuntu:  sudo apt install rsync"
  echo "  Windows: use WSL or Git Bash, or install via winget/scoop"
  exit 1
fi

# Build exclude flags
EXCLUDE_FLAGS=()
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
  EXCLUDE_FLAGS+=(--exclude "$pattern")
done

# ──────────────────────────────────────────────
# Sync
# ──────────────────────────────────────────────
REMOTE_DEST="${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DATA_DIR}"

echo "═══════════════════════════════════════════"
echo " GSV Tracker Data Sync"
echo "═══════════════════════════════════════════"

if [[ -n "$SINGLE_FILE" ]]; then
  SRC="${LOCAL_DATA_DIR}/${SINGLE_FILE}"
  if [[ ! -f "$SRC" ]]; then
    echo "Error: File not found: $SRC"
    exit 1
  fi

  # Ensure remote subdirectory exists for nested paths
  REMOTE_SUBDIR="$(dirname "$SINGLE_FILE")"
  if [[ "$REMOTE_SUBDIR" != "." ]]; then
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_DATA_DIR}/${REMOTE_SUBDIR}'"
  fi

  echo "  File:   $SINGLE_FILE"
  echo "  Remote: ${REMOTE_DEST}/${SINGLE_FILE}"
  [[ -n "$DRY_RUN" ]] && echo "  Mode:   DRY RUN"
  echo ""

  # Sync the single file with appropriate permissions (directories 2755, files 644)
  # - D2755: Sets directories to drwxr-sr-x. The 2 preserves the SetGID bit (s), which 
  #   ensures any new subdirectories correctly inherit the makelab group
  # - F644: Sets files to -rw-r--r--, which is standard for web-accessible files
  rsync -azh --chmod=D2755,F644 --progress $DRY_RUN $VERBOSE \
    "$SRC" \
    "${REMOTE_DEST}/${SINGLE_FILE}"
else
  FILE_COUNT=$(find "$LOCAL_DATA_DIR" -type f | wc -l | tr -d ' ')
  DIR_SIZE=$(du -sh "$LOCAL_DATA_DIR" 2>/dev/null | cut -f1)

  echo "  Local:  $LOCAL_DATA_DIR ($FILE_COUNT files, ${DIR_SIZE})"
  echo "  Remote: $REMOTE_DEST"
  [[ -n "$DRY_RUN" ]] && echo "  Mode:   DRY RUN"
  [[ -n "$DELETE" ]] && echo "  Delete: enabled (remote files not in local will be removed)"
  echo ""

  rsync -azh --chmod=D2755,F644 --progress $DRY_RUN $VERBOSE $DELETE \
    "${EXCLUDE_FLAGS[@]}" \
    "$LOCAL_DATA_DIR/" \
    "${REMOTE_DEST}/"
fi

echo ""
if [[ -n "$DRY_RUN" ]]; then
  echo "Dry run complete. No files were transferred."
else
  echo "Sync complete."
  echo "Data accessible at: https://makeabilitylab.cs.washington.edu/public/gsv-tracker/data/"
fi

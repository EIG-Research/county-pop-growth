#!/usr/bin/env bash
# template_reset.sh — scrub the project records under records/ back to their
# fresh-template baseline before distributing this template into a new
# project. Removes dated plans, specs, session logs, war-room ledgers, and review
# boards that accumulated during template development so they do not ship into
# copies. War-room ledgers are per-script records of one project's code decisions;
# carrying them into an unrelated project would be actively misleading.
#
# Preserved in records/ and in every record folder: README.md and .gitkeep.
# Everything else under these directories is removed, including anything at the
# top of records/ other than the record folders themselves.

# The code, data, drafts, and output directories are never touched.
#
# Also removes Infrastructure/.template-identity, the marker that tells the
# SessionStart hook this checkout is the template itself. Dropping it here is what
# re-arms the PROJECT.md title requirement in the new project: reset is step 1 of
# porting, so the requirement activates exactly when it starts mattering.
#
# Usage:
#   bash Infrastructure/scripts/template_reset.sh [--dry-run] [--yes]
#
#   --dry-run   List what would be removed; change nothing.
#   --yes       Skip the interactive confirmation prompt.
set -euo pipefail

# Resolve repo root from this script's location (scripts/ is one level under Infrastructure/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

WORKSPACE_DIRS=(
  "records/plans"
  "records/specs"
  "records/session_logs"
  "records/war_rooms"
  "records/review_boards"
)

RECORDS_ROOT="records"

# Names preserved in records/ and in every workspace dir.
KEEP=("README.md" ".gitkeep")

DRY_RUN=false
ASSUME_YES=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --yes|-y)  ASSUME_YES=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# A project made by copying the template into an empty repository can keep the
# .gitattributes GitHub wrote for it, which lacks eol=lf; on Windows the checks then
# see CRLF files and fail. Warn (in a dry run too) without changing anything.
if ! grep -qE '^\*[[:space:]]+text=auto[[:space:]]+eol=lf([[:space:]]|$)' \
    "$REPO_ROOT/.gitattributes" 2>/dev/null; then
  echo "WARNING: .gitattributes does not set '* text=auto eol=lf'. Copy the template's" >&2
  echo "  .gitattributes into this repository, then run 'git add --renormalize .' and commit" >&2
  echo "  (README, Getting started, step 2)." >&2
fi

is_kept() {
  local base="$1"
  for k in "${KEEP[@]}"; do
    [ "$base" = "$k" ] && return 0
  done
  return 1
}

is_workspace_dir() {
  local rel="$1"
  for w in "${WORKSPACE_DIRS[@]}"; do
    [ "$rel" = "$w" ] && return 0
  done
  return 1
}

# Collect removal targets (top-level entries inside each workspace dir that
# are not in KEEP). Directories are removed recursively.
targets=()
if [ -d "$REPO_ROOT/$RECORDS_ROOT" ]; then
  while IFS= read -r entry; do
    base="$(basename "$entry")"
    is_kept "$base" && continue
    is_workspace_dir "$RECORDS_ROOT/$base" && [ -d "$entry" ] && continue
    targets+=("$entry")
  done < <(find "$REPO_ROOT/$RECORDS_ROOT" -mindepth 1 -maxdepth 1 | sort)
fi
for rel in "${WORKSPACE_DIRS[@]}"; do
  dir="$REPO_ROOT/$rel"
  [ -d "$dir" ] || continue
  while IFS= read -r entry; do
    base="$(basename "$entry")"
    is_kept "$base" && continue
    targets+=("$entry")
  done < <(find "$dir" -mindepth 1 -maxdepth 1 | sort)
done

TEMPLATE_MARKER="$REPO_ROOT/Infrastructure/.template-identity"
if [ -f "$TEMPLATE_MARKER" ]; then
  targets+=("$TEMPLATE_MARKER")
fi

if [ "${#targets[@]}" -eq 0 ]; then
  echo "Workspace already at template baseline; nothing to remove."
  exit 0
fi

echo "Template reset will remove:"
for t in "${targets[@]}"; do
  echo "  - ${t#$REPO_ROOT/}"
done

if [ "$DRY_RUN" = true ]; then
  echo "(--dry-run: no changes made.)"
  exit 0
fi

if [ "$ASSUME_YES" != true ]; then
  printf "Proceed with removal? [y/N] "
  read -r reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "Aborted; no changes made."; exit 0 ;;
  esac
fi

for t in "${targets[@]}"; do
  rm -rf "$t"
done

echo "Template reset complete. Preserved README.md / .gitkeep in records/ and each record folder."
if [ -n "${TEMPLATE_MARKER:-}" ] && [ ! -f "$TEMPLATE_MARKER" ]; then
  echo "Removed Infrastructure/.template-identity: this is now a project, not the template."
  echo "Set the Research Project Title in PROJECT.md before substantive work."
fi
echo "Review with 'git status' and commit the cleaned workspace before distributing."

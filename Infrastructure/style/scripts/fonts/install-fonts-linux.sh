#!/usr/bin/env bash
# Install the EIG primary fonts (Open Sans, Source Serif 4) for the current user.
#   bash Infrastructure/style/scripts/fonts/install-fonts-linux.sh
# Installs into ~/.local/share/fonts/eig, or EIG_FONT_DIR when set (the macOS installer
# sets it to ~/Library/Fonts). Sources and SHA-256 checksums come from font-sources.tsv
# next to this script. Each file downloads to a temporary directory and is installed
# only when its checksum matches, so a failed or altered download installs nothing.
# Every font is attempted. Exit codes: 0 all installed; 1 a download failed, a
# checksum did not match, or a required tool is missing; 2 fontconfig does not list a
# family afterwards.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCES="${SCRIPT_DIR}/font-sources.tsv"
FONT_DIR="${EIG_FONT_DIR:-${HOME}/.local/share/fonts/eig}"

if command -v curl >/dev/null 2>&1; then
  fetch() { curl -L --fail --silent --show-error "$1" -o "$2"; }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -q -O "$2" "$1"; }
else
  echo "ERROR: curl or wget is required." >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  sha256_of() { sha256sum "$1" | cut -d ' ' -f 1; }
elif command -v shasum >/dev/null 2>&1; then
  sha256_of() { shasum -a 256 "$1" | cut -d ' ' -f 1; }
else
  echo "ERROR: sha256sum or shasum is required to verify the downloads." >&2
  exit 1
fi

if [ ! -f "${SOURCES}" ]; then
  echo "ERROR: font source list not found: ${SOURCES}" >&2
  exit 1
fi

DOWNLOAD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/eig-fonts.XXXXXX")" || exit 1
trap 'rm -rf "${DOWNLOAD_DIR}"' EXIT

mkdir -p "${FONT_DIR}"
failed=()
families=()
while IFS=$'\t' read -r family style file sha256 url; do
  case "${family}" in ''|'#'*|family) continue ;; esac
  echo "Downloading ${family} ${style}..."
  download="${DOWNLOAD_DIR}/${file}"
  if ! fetch "${url}" "${download}"; then
    echo "ERROR: download failed: ${url}" >&2
    failed+=("${file}")
    continue
  fi
  actual="$(sha256_of "${download}")"
  if [ "${actual}" != "${sha256}" ]; then
    echo "ERROR: checksum mismatch for ${file}: expected ${sha256}, got ${actual}; not installed." >&2
    failed+=("${file}")
    continue
  fi
  mv "${download}" "${FONT_DIR}/${file}"
  families+=("${family}")
done < "${SOURCES}"

if command -v fc-cache >/dev/null 2>&1; then
  fc-cache -f "${FONT_DIR}"
elif [ "$(uname -s)" != "Darwin" ]; then
  echo "WARNING: fc-cache not found. You may need to refresh the font cache manually." >&2
fi

if [ "${#failed[@]}" -gt 0 ]; then
  echo "ERROR: ${#failed[@]} font file(s) were not installed: ${failed[*]}" >&2
  exit 1
fi

if [ "${#families[@]}" -eq 0 ]; then
  echo "ERROR: ${SOURCES} lists no fonts." >&2
  exit 1
fi

if command -v fc-list >/dev/null 2>&1; then
  while IFS= read -r family; do
    if ! fc-list | grep -qi -- "${family}"; then
      echo "ERROR: ${family} not listed by fontconfig after installation." >&2
      exit 2
    fi
  done < <(printf '%s\n' "${families[@]}" | sort -u)
fi

echo "Font installation complete. Restart R, Python, or Stata sessions before plotting."

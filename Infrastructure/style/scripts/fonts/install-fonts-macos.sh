#!/usr/bin/env bash
# Install the EIG primary fonts (Open Sans, Source Serif 4) for the current user on macOS.
#   bash Infrastructure/style/scripts/fonts/install-fonts-macos.sh
# Uses the same pinned, checksum-verified sources as Linux (font-sources.tsv), so every
# platform installs byte-identical files. Installs into ~/Library/Fonts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export EIG_FONT_DIR="${EIG_FONT_DIR:-${HOME}/Library/Fonts}"
exec bash "${SCRIPT_DIR}/install-fonts-linux.sh"

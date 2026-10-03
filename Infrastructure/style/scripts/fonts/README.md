# Font Setup and Validation

These scripts install the EIG primary fonts and check that R, Python, and Stata can draw with them.

## Families

The token file `Infrastructure/style/tokens/eig-style-tokens.v1.json` owns the families (`typography.headline` and `typography.body`):

- Headline: Source Serif Pro. The tokens accept Source Serif 4, its current release, as primary (`accept_as_primary`), and the installers install Source Serif 4.
- Body: Open Sans.

A family in `fallback_stack` passes a check only with the allow-fallback option.

## Install

Run the installer for your platform from the repository root. Each installs for the current user and asks for no administrator rights.

- macOS: `bash Infrastructure/style/scripts/fonts/install-fonts-macos.sh` (into `~/Library/Fonts`).
- Linux: `bash Infrastructure/style/scripts/fonts/install-fonts-linux.sh` (into `~/.local/share/fonts/eig`).
- Windows: `powershell -ExecutionPolicy Bypass -File Infrastructure\style\scripts\fonts\install-fonts-windows.ps1`.

All three installers read `font-sources.tsv`: a URL pinned to a commit or release tag, and the file's SHA-256. A tag can move, so each file is installed only when its checksum matches; a failed or altered download installs nothing. The installers try every font, report each failure, and exit non-zero if any font was not installed. The macOS installer runs the Linux one with a different font directory. To confirm the URLs still resolve and the checksums still match, run `python3 Infrastructure/scripts/test_style.py --network`; it hashes the files in memory and writes nothing.

## Check

Each checker passes when every role resolves to a primary or accepted family, and exits non-zero otherwise. Add the fallback option to pass on a fallback family.

| Language | Strict | Fallback allowed |
|---|---|---|
| Python | `python3 Infrastructure/style/scripts/fonts/check-fonts.py` | `--allow-fallback` |
| R | `Rscript Infrastructure/style/scripts/fonts/check-fonts.R` | `--allow-fallback` |
| Stata | `do Infrastructure/style/scripts/fonts/check-fonts.do` | `allow_fallback` |

The R and Python checkers use their theme's font resolver, so they pass exactly when the theme would draw with a primary family. The Stata checker reads the same lists from the generated `themes/stata/eig_tokens.do` and records the first family that passed in `EIG_FONT_HEADLINE_RESOLVED` and `EIG_FONT_BODY_RESOLVED`, which `eig_graph_defaults` uses. Stata may accept a font name it does not have, so its check can pass when the font is missing (unverified: no Stata was available when it was written).

Stata's `graph set` font settings persist across Stata sessions, not just the current one. The checker probes each candidate by setting it as the window font, then resets the window font to Stata's default; `eig_graph_defaults` sets the EIG fonts afterwards.

Run the check at project startup and stop the pipeline on a non-zero exit.

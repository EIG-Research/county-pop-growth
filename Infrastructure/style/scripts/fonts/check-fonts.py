#!/usr/bin/env python3
"""Report whether the EIG headline and body fonts are installed.

Uses the Python theme's resolver, so it passes exactly when the theme would draw with a
primary family (or one the tokens accept as primary, such as Source Serif 4).

    python3 Infrastructure/style/scripts/fonts/check-fonts.py [--allow-fallback]

Exit codes: 0 pass, 1 fonts missing, 2 the check could not run.
"""

import argparse
import sys
from pathlib import Path

THEME_DIR = Path(__file__).resolve().parents[2] / "themes" / "python"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate required EIG fonts.")
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Pass when a role resolves to a fallback family instead of a primary one.",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(THEME_DIR))
    try:
        import eig_theme
    except ImportError as exc:
        print(f"ERROR: cannot load the Python theme from {THEME_DIR}: {exc}", file=sys.stderr)
        return 2

    families = eig_theme.installed_font_families()
    if not families:
        print(
            "ERROR: Unable to enumerate installed fonts. Install matplotlib or fontconfig tools.",
            file=sys.stderr,
        )
        return 2

    failed = False
    for role in ("headline", "body"):
        primary = eig_theme.TYPOGRAPHY[role]["primary_family"]
        family, is_primary = eig_theme.resolve_font_family(role, families, warn=False)
        if is_primary:
            print(f"OK {role}: {family}")
        else:
            print(f"FALLBACK {role}: {family} (primary {primary} is not installed)")
            failed = failed or not args.allow_fallback

    if failed:
        print(
            "ERROR: Required EIG fonts are missing. Run an installer in "
            "Infrastructure/style/scripts/fonts/ and restart the session.",
            file=sys.stderr,
        )
        return 1
    print("PASS: EIG fonts resolve" + (" (fallbacks allowed)." if args.allow_fallback else " to primary families."))
    return 0


if __name__ == "__main__":
    sys.exit(main())

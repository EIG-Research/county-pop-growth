#!/bin/sh
# Run a hook script with the first real Python on PATH: python3, then python, then the
# Windows `py -3` launcher. On Windows, `python3` is often the Microsoft Store alias stub in
# WindowsApps, which prints an install hint and exits 9009 instead of running anything, so
# a command that resolves there is skipped. The hooks run on every tool call, so this checks
# where each name resolves instead of starting an interpreter to ask.
for name in python3 python; do
  found=$(command -v "$name" 2>/dev/null) || continue
  case "$found" in
    *WindowsApps*) continue ;;
  esac
  exec "$name" "$@"
done
if command -v py >/dev/null 2>&1; then
  exec py -3 "$@"
fi
echo "hook: no Python found (tried python3, python, py -3); see README.md, Getting started" >&2
exit 1

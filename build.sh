#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# Spica. Rebuild the single-file executable in dist/.
#
#   ./build.sh
#
# Sets up whatever is missing first (a private Python, Node, PyInstaller),
# all of it inside runtime/, then redraws the icon, builds the interface and
# packages dist/Spica.exe. Nothing is installed on the machine.
# ---------------------------------------------------------------------------
set -eu
exec "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/run.sh" --build "$@"

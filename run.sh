#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# Spica. Starts the app, setting up its own runtime the first time.
#
#   ./run.sh                 the desktop window
#   ./run.sh --cli PCSK9     a record in the terminal (needs nothing installed)
#   ./run.sh --dev           the window against the Vite dev server
#   ./run.sh --setup         set up the runtime and stop
#
# Works from anywhere: every path is resolved from this script's own location,
# so the folder can be moved, renamed or carried on a drive with a different
# letter. Nothing is installed on the machine. Everything this creates lives
# in runtime/, which can be deleted to undo it.
# ---------------------------------------------------------------------------
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

# The runtime, if a previous run already built it.
for candidate in runtime/Scripts/python.exe runtime/bin/python3 runtime/python.exe; do
    if [ -x "$candidate" ] || [ -f "$candidate" ]; then
        exec "./$candidate" tools/bootstrap.py "$@"
    fi
done

# Otherwise any Python will do to get started; the bootstrap builds the rest.
for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if [ "$candidate" = "py" ]; then
            exec py -3 tools/bootstrap.py "$@"
        fi
        exec "$candidate" tools/bootstrap.py "$@"
    fi
done

# No Python at all. On Windows that is recoverable without installing one:
# the embeddable build is a working interpreter in a zip, and both curl and
# tar ship with Windows 10 and 11.
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW* | MSYS* | CYGWIN* | Windows_NT)
        VERSION=3.13.9
        case "$(uname -m)" in aarch64 | arm64) ARCH=arm64 ;; *) ARCH=amd64 ;; esac
        URL="https://www.python.org/ftp/python/$VERSION/python-$VERSION-embed-$ARCH.zip"
        echo "[spica] no Python found. Downloading one into runtime/ (about 11 MB)."
        mkdir -p runtime
        curl -fL --progress-bar -o runtime/python-embed.zip "$URL"
        tar -xf runtime/python-embed.zip -C runtime
        rm -f runtime/python-embed.zip
        exec ./runtime/python.exe tools/bootstrap.py "$@"
        ;;
esac

echo "[spica] no Python found on this machine."
echo "        Install Python 3.11 or newer and run this again. Nothing else"
echo "        needs installing: Spica sets up the rest itself, inside runtime/."
exit 1

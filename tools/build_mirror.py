"""Build the local data mirror. This is the command line of the builder,
`spica/mirrorbuild.py`. The app can also run it (Settings, "Local data").

    python tools/build_mirror.py                  # every source
    python tools/build_mirror.py hpa clinvar      # these sources only
    python tools/build_mirror.py --refresh gtex   # download again even if present
    python tools/build_mirror.py --check          # which sources have a newer release
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spica.mirrorbuild import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

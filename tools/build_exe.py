"""Build `dist/Spica.exe`: one file, nothing to install, nothing to unpack.

    ./build.sh        macOS, Linux, Git Bash or WSL on Windows
    build.cmd         Windows

Both are wrappers. They find the runtime as `run.sh` does and then call
this file. The build prepares all it needs first, so a fresh clone builds
with one command.

    1. the icon, redrawn from the logo component
    2. the interface, built with npm into frontend/dist
    3. the third-party notices, regenerated from what the runtime holds
    4. PyInstaller, installed into runtime/ and not onto the machine
    5. the exe, with LICENSE and THIRD_PARTY_NOTICES.md inside and beside it

Inside the exe: Python, pywebview, the data layer and the built interface.
Never inside: `tools/`. Outside the exe: the mirror and the fetch cache, in
`data/` beside the exe (see `spica/paths.py`). A rebuild thus never
discards gigabytes of databases.

On macOS and Linux this produces a `Spica` binary, not an exe. The build is
the same; only the launchers differ.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bootstrap import ROOT, WINDOWS, ensure_frontend, ensure_runtime, say  # noqa: E402

DIST = ROOT / "dist"
WORK = ROOT / "build"
ICON = ROOT / "assets" / "spica.ico"
UI_FILE = ROOT / "frontend" / "dist" / "index.html"
NAME = "Spica"
#: Shipped inside the exe (Settings shows them) and beside it.
DOCUMENTS = ("LICENSE", "THIRD_PARTY_NOTICES.md")
#: The readers AI mode uses for the user's documents. Imported lazily, so
#: PyInstaller's scan cannot see them; named here when installed.
READERS = ("pdfminer", "openpyxl", "docx", "pptx", "charset_normalizer")


def ensure_icon(python: Path) -> bool:
    """Redraw the icon, so it always matches the logo in the interface."""
    done = subprocess.run([str(python), str(ROOT / "tools" / "make_icon.py")])
    return done.returncode == 0 and ICON.exists()


def has_llama(python: Path) -> bool:
    """Whether the model runtime is installed. The exe carries it only if so.

    Without it the exe is about 12 MB and the agent panel falls back to its
    stand-in; with it the exe is larger and runs a real model. Either is a
    legitimate build, so this follows the runtime rather than deciding.
    """
    return subprocess.run(
        [str(python), "-c", "import llama_cpp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def has_readers(python: Path) -> bool:
    """Whether the document readers are installed. Like the model, the exe carries
    them only if the runtime has them (`./run.sh --agents` installs both)."""
    probe = "import " + ", ".join(READERS)
    return subprocess.run([str(python), "-c", probe], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def has_module(python: Path, name: str) -> bool:
    return subprocess.run([str(python), "-c", f"import {name}"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def ensure_notices(python: Path) -> bool:
    done = subprocess.run([str(python), str(ROOT / "tools" / "notices.py")])
    return done.returncode == 0


def ensure_pyinstaller(python: Path) -> bool:
    check = subprocess.run(
        [str(python), "-m", "PyInstaller", "--version"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if check.returncode == 0:
        return True
    say("installing PyInstaller into the runtime (build only, not shipped)")
    done = subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         "--no-warn-script-location", "pyinstaller"],
    )
    return done.returncode == 0


def build(python: Path) -> int:
    command = [
        str(python), "-m", "PyInstaller",
        "--onefile",
        "--name", NAME,
        "--noconsole",  # the window is the interface; no terminal behind it
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(WORK / "pyinstaller"),
        "--specpath", str(WORK),
        # The interface is one self-contained file, bundled where
        # spica.paths.bundled() looks for it.
        "--add-data", f"{UI_FILE}{os.pathsep}frontend/dist",
        # The fonts the exported client report embeds, and their licences
        # (spica/export.py reads them beside its own module).
        "--add-data", f"{ROOT / 'spica' / 'assets'}{os.pathsep}spica/assets",
        # Nothing from tools/ is imported by the app; saying so keeps it so.
        "--exclude-module", "tools",
        # pywebview loads its platform backend and its javascript at runtime,
        # so neither is visible to PyInstaller's import scan.
        "--collect-all", "webview",
    ]
    if ICON.exists():
        command += ["--icon", str(ICON)]
    if WINDOWS:
        # pythonnet's loader is reached through clr, which is imported by name.
        command += ["--hidden-import", "clr", "--collect-all", "clr_loader"]
    if has_llama(python):
        # Its native libraries are data to PyInstaller, not imports, so they
        # only come along if collected whole.
        say("including the local model runtime")
        command += ["--collect-all", "llama_cpp"]
    if has_module(python, "_pywhispercpp") and has_module(python, "miniaudio"):
        # The digest's transcription engine: whisper.cpp's bindings and the
        # audio decoder, with their native libraries.
        say("including the transcription engine")
        command += ["--hidden-import", "_pywhispercpp", "--hidden-import", "miniaudio",
                    "--hidden-import", "_miniaudio"]
    if has_module(python, "pyarrow"):
        # The mirror builder reads Open Targets' Parquet with it, imported
        # only when Settings updates the data; named so it is bundled.
        say("including the Parquet reader for mirror updates")
        command += ["--hidden-import", "pyarrow.parquet", "--collect-submodules", "pyarrow",
                    "--collect-binaries", "pyarrow", "--collect-data", "pyarrow"]
    if has_module(python, "pydeseq2"):
        # Differential expression (spica/geo/de.py), imported only when a
        # DESeq2 run starts; named so it is bundled with what it imports.
        # session_info2 comes with anndata, is never imported, and is MPL-2.0.
        say("including DESeq2 (PyDESeq2) for differential expression")
        command += ["--hidden-import", "spica.geo.de", "--collect-submodules", "pydeseq2",
                    "--collect-submodules", "anndata", "--collect-data", "anndata",
                    "--collect-submodules", "formulaic", "--exclude-module", "session_info2"]
    if has_readers(python):
        say("including the document readers")
        for module in READERS:
            command += ["--hidden-import", module, "--collect-submodules", module]
    for name in DOCUMENTS:
        command += ["--add-data", f"{ROOT / name}{os.pathsep}."]
    command.append(str(ROOT / "app.py"))

    say("building, which takes a minute")
    return subprocess.run(command, cwd=ROOT).returncode


def signtool() -> Path | None:
    """Windows SDK's signtool, if the SDK is installed: newest version first."""
    override = os.environ.get("SPICA_SIGNTOOL", "").strip()
    if override:
        return Path(override) if Path(override).exists() else None
    found = shutil.which("signtool")
    if found:
        return Path(found)
    kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    candidates = sorted(kits.glob("*/x64/signtool.exe"), reverse=True) if kits.exists() else []
    return candidates[0] if candidates else None


def sign(produced: Path) -> bool | None:
    """Authenticode-sign the exe when a certificate is configured, and say so.

    The certificate is the owner's and never enters the repository:
    SPICA_SIGN_PFX (a .pfx file) with SPICA_SIGN_PASSWORD, or
    SPICA_SIGN_THUMBPRINT for one in the Windows certificate store (a hardware
    token's included). Timestamped, so the signature outlives the certificate.
    None when nothing is configured: the build is then unsigned, and says so."""
    pfx = os.environ.get("SPICA_SIGN_PFX", "").strip()
    thumbprint = os.environ.get("SPICA_SIGN_THUMBPRINT", "").strip()
    if not pfx and not thumbprint:
        return None
    tool = signtool()
    if tool is None:
        say("signing asked for, but signtool was not found: install the Windows SDK, or set "
            "SPICA_SIGNTOOL to its path")
        return False
    command = [str(tool), "sign", "/fd", "SHA256", "/td", "SHA256",
               "/tr", os.environ.get("SPICA_SIGN_TIMESTAMP", "http://timestamp.digicert.com")]
    if pfx:
        command += ["/f", pfx]
        if os.environ.get("SPICA_SIGN_PASSWORD"):
            command += ["/p", os.environ["SPICA_SIGN_PASSWORD"]]
    else:
        command += ["/sha1", thumbprint]
    command.append(str(produced))
    if subprocess.run(command).returncode != 0:
        say("signing failed; the exe is built but unsigned")
        return False
    verified = subprocess.run([str(tool), "verify", "/pa", str(produced)]).returncode == 0
    say("signed and verified" if verified else "signed, but the signature did not verify")
    return verified


def main(argv: list[str] | None = None) -> int:
    python = ensure_runtime()

    if not ensure_icon(python):
        say("the icon could not be drawn; building without one")
    if not UI_FILE.exists() and not ensure_frontend():
        say("the interface has to be built before the exe can bundle it.")
        return 1
    if not ensure_notices(python):
        say("the third-party notices could not be written.")
        return 1
    if not ensure_pyinstaller(python):
        say("PyInstaller could not be installed.")
        return 1

    code = build(python)
    if code != 0:
        say("the build failed; the output above says where.")
        return code

    produced = DIST / (f"{NAME}.exe" if WINDOWS else NAME)
    if not produced.exists():
        say(f"the build reported success but {produced} is not there.")
        return 1

    signed = sign(produced) if WINDOWS else None
    if signed is None:
        say("unsigned: set SPICA_SIGN_PFX or SPICA_SIGN_THUMBPRINT to sign (docs/licensing.md)")
    for name in DOCUMENTS:
        shutil.copyfile(ROOT / name, DIST / name)
    megabytes = produced.stat().st_size / (1024 * 1024)
    say(f"built {produced} ({megabytes:.0f} MB)")
    say("it needs nothing installed. Its data lands in a data/ folder beside it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

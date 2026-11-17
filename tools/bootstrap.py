"""Set up the Spica runtime, then start the app.

Use `run.sh` or `run.cmd`, not this file directly. They find a Python and
call this file, which does the rest.

The steps, each skipped when it is already done:

1. **A private interpreter** in `runtime/`: a virtual environment from the
   Python that was found. On Windows without any Python, the official
   embeddable build: a complete CPython in about 11 MB that installs and
   registers nothing.
2. **The dependencies** from `requirements.txt`, into that runtime only.
3. **The interface**, built once with npm into `frontend/dist`.
4. **The app**, started with the Python of the runtime.

Nothing is installed on the machine, the PATH does not change, and nothing
outside `runtime/` is written. A deletion of that one folder undoes all of
it.

`--cli` skips steps 2 and 3. The terminal record needs only the standard
library, so it runs on a bare machine. `--agents` adds the local model
runtime, which is optional and not in `requirements.txt`. `--build`
packages the app into one executable and does not start it; see
`tools/build_exe.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
STAMP = RUNTIME / "installed.json"
REQUIREMENTS = ROOT / "requirements.txt"
AGENT_REQUIREMENTS = ROOT / "requirements-agents.txt"
LLAMA_WHEELS = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
UI_FILE = ROOT / "frontend" / "dist" / "index.html"

MINIMUM = (3, 11)  # the app's own floor; the bootstrap itself runs on 3.9
EMBED_VERSION = "3.13.9"
EMBED_URL = (
    "https://www.python.org/ftp/python/{v}/python-{v}-embed-{arch}.zip"
)
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"

# Only used when the machine has no Node at all and the interface has not
# been built yet. Pinned rather than resolved: the build should not change
# because an LTS line moved on. Bump it deliberately; nodejs.org keeps every
# release, so an old pin never stops working.
NODE_VERSION = "v24.22.1"
NODE_URL = "https://nodejs.org/dist/{v}/{name}"

WINDOWS = os.name == "nt"


def say(message: str) -> None:
    print(f"[spica] {message}", flush=True)


# -- the runtime ------------------------------------------------------------


def runtime_python() -> Path | None:
    """The interpreter in `runtime/`, however it got there."""
    for candidate in (
        RUNTIME / "Scripts" / "python.exe",  # a virtual environment on Windows
        RUNTIME / "bin" / "python3",  # ...and everywhere else
        RUNTIME / "python.exe",  # the embeddable build
    ):
        if candidate.exists():
            return candidate
    return None


def inside_runtime() -> bool:
    try:
        Path(sys.executable).resolve().relative_to(RUNTIME.resolve())
        return True
    except (ValueError, OSError):
        return False


def embed_arch() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "amd64"


def download_embeddable() -> Path:
    """Fetch the embeddable CPython into `runtime/`.

    Windows only, and only when the machine has no Python of its own. It is
    a zip of a working interpreter: unpacked, it is complete, and it touches
    neither the registry nor PATH.
    """
    import zipfile

    url = EMBED_URL.format(v=EMBED_VERSION, arch=embed_arch())
    RUNTIME.mkdir(parents=True, exist_ok=True)
    archive = RUNTIME / "python-embed.zip"
    say(f"downloading Python {EMBED_VERSION} ({embed_arch()}), about 11 MB")
    urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(RUNTIME)
    archive.unlink()
    enable_site_packages()
    return RUNTIME / "python.exe"


def enable_site_packages() -> None:
    """Let the embeddable build see installed packages.

    It ships with a `._pth` file that pins `sys.path` and turns `site` off.
    This makes it embeddable, and it also stops pip until the line is
    uncommented.
    """
    for pth in RUNTIME.glob("python*._pth"):
        text = pth.read_text(encoding="utf-8")
        if "\nimport site" in text and not text.count("#import site"):
            continue
        text = text.replace("#import site", "import site")
        if "Lib\\site-packages" not in text:
            text = text.rstrip("\n") + "\nLib\\site-packages\n"
        pth.write_text(text, encoding="utf-8")


def ensure_pip(python: Path) -> None:
    if subprocess.run(
        [str(python), "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0:
        return
    say("installing pip into the runtime")
    installer = RUNTIME / "get-pip.py"
    urllib.request.urlretrieve(GET_PIP, installer)
    subprocess.run([str(python), str(installer), "--no-warn-script-location"], check=True)
    installer.unlink(missing_ok=True)


def ensure_runtime() -> Path:
    """The interpreter Spica will run under, creating it if it is not there."""
    existing = runtime_python()
    if existing:
        return existing

    if inside_runtime():  # the embeddable build, unpacked by the launcher
        enable_site_packages()
        return Path(sys.executable)

    if sys.version_info >= MINIMUM:
        import venv

        say(f"creating a private runtime in {RUNTIME.name}/ "
            f"(Python {'.'.join(str(n) for n in sys.version_info[:3])})")
        venv.EnvBuilder(with_pip=True, symlinks=not WINDOWS).create(RUNTIME)
        created = runtime_python()
        if created:
            return created

    if WINDOWS:
        return download_embeddable()

    version = ".".join(str(number) for number in sys.version_info[:3])
    raise SystemExit(
        f"[spica] this machine's Python is {version}, and Spica needs "
        f"{MINIMUM[0]}.{MINIMUM[1]} or newer.\n"
        f"        Install a newer Python and run this again; nothing else "
        f"on the machine will be touched."
    )


# -- the dependencies -------------------------------------------------------


def requirements_hash() -> str:
    data = REQUIREMENTS.read_bytes() if REQUIREMENTS.exists() else b""
    return hashlib.sha256(data).hexdigest()[:16]


def ensure_dependencies(python: Path) -> bool:
    """Install `requirements.txt` into the runtime, once per change."""
    wanted = requirements_hash()
    if STAMP.exists():
        try:
            if json.loads(STAMP.read_text(encoding="utf-8")).get("requirements") == wanted:
                return True
        except (OSError, json.JSONDecodeError):
            pass

    ensure_pip(python)
    say("installing dependencies")
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         "--no-warn-script-location", "-r", str(REQUIREMENTS)],
    )
    if result.returncode != 0:
        say("dependencies could not be installed. The terminal version needs "
            "none of them: try `--cli PCSK9`.")
        return False
    STAMP.write_text(json.dumps({"requirements": wanted}, indent=1), encoding="utf-8")
    return True


#: The transcription engine for the digest, and what decodes the audio:
#: both MIT, both prebuilt. Installed without their own dependencies, whose
#: convenience layers bring licences the exe does not ship.
SPEECH_PACKAGES = ("pywhispercpp==1.5.1", "miniaudio==1.71")


def install_speech(python: Path) -> bool:
    """Add whisper.cpp (through pywhispercpp) and miniaudio to the runtime."""
    ensure_pip(python)
    say("installing the transcription engine (whisper.cpp, prebuilt)")
    base = [str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-warn-script-location", "--only-binary=:all:"]
    done = subprocess.run(base + ["numpy", "cffi"]).returncode == 0 and \
        subprocess.run(base + ["--no-deps", *SPEECH_PACKAGES]).returncode == 0
    if not done:
        say("the transcription engine could not be installed. The digest still lists "
            "episodes, with their show notes and any transcript the publisher gives.")
        return False
    say("done. Download a speech model in Digest, Sources.")
    return True


def install_agents(python: Path) -> bool:
    """Add llama-cpp-python to the runtime, from the prebuilt wheel index.

    Not in `requirements.txt`, by design. It is tens of megabytes of native
    code that most of Spica does not need. Without it, the agent panel says
    so plainly; it does not fail.
    """
    ensure_pip(python)
    say("installing the local model runtime (prebuilt wheels, no compiler)")
    done = subprocess.run([
        str(python), "-m", "pip", "install", "--disable-pip-version-check",
        "--no-warn-script-location", "--only-binary=:all:",
        "--extra-index-url", LLAMA_WHEELS,
        "-r", str(AGENT_REQUIREMENTS),
    ])
    if done.returncode != 0:
        say("the model runtime could not be installed. Spica still runs; the "
            "agent panel will use its scripted stand-in.")
        return False
    say("done. Put a .gguf file in data/models and the agents will use it.")
    return True


# -- the interface ----------------------------------------------------------


def node_archive() -> str:
    """The Node release file for this machine."""
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if WINDOWS:
        return f"node-{NODE_VERSION}-win-{'arm64' if arm else 'x64'}.zip"
    if sys.platform == "darwin":
        return f"node-{NODE_VERSION}-darwin-{'arm64' if arm else 'x64'}.tar.gz"
    return f"node-{NODE_VERSION}-linux-{'arm64' if arm else 'x64'}.tar.xz"


def local_npm() -> Path | None:
    """npm inside `runtime/node`, if a previous run put it there."""
    base = RUNTIME / "node"
    if not base.exists():
        return None
    for folder in sorted(base.iterdir()):
        for candidate in (folder / "npm.cmd", folder / "bin" / "npm"):
            if candidate.exists():
                return candidate
    return None


def download_node() -> Path | None:
    """Fetch a portable Node into `runtime/node`, for the one build step.

    Same bargain as the Python runtime: unpacked in place, nothing
    installed, nothing on PATH, and deleting `runtime/` undoes it.
    """
    import tarfile
    import zipfile

    name = node_archive()
    base = RUNTIME / "node"
    base.mkdir(parents=True, exist_ok=True)
    archive = base / name
    say(f"downloading Node {NODE_VERSION} to build the interface, about 30 MB")
    try:
        urllib.request.urlretrieve(NODE_URL.format(v=NODE_VERSION, name=name), archive)
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(base)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(base, filter="data")
    except Exception as exc:
        say(f"Node could not be downloaded: {exc}")
        return None
    finally:
        archive.unlink(missing_ok=True)
    return local_npm()


def ensure_frontend() -> bool:
    """Build `frontend/dist/index.html` if it is not already there."""
    if UI_FILE.exists():
        return True

    npm = shutil.which("npm") or local_npm() or download_node()
    if not npm:
        say("the interface cannot be built without Node.")
        say("Install Node.js and run this again, or read records in the "
            "terminal instead: `--cli PCSK9`.")
        return False

    # A downloaded npm still calls `node`, which is beside it rather than
    # on this machine's PATH.
    environment = dict(os.environ)
    node_bin = Path(npm).parent
    environment["PATH"] = f"{node_bin}{os.pathsep}{environment.get('PATH', '')}"

    frontend = ROOT / "frontend"
    install = ["ci"] if (frontend / "package-lock.json").exists() else ["install"]
    say("building the interface (first run only, a minute or two)")
    for command in (install, ["run", "build"]):
        done = subprocess.run([str(npm), *command], cwd=frontend, env=environment,
                              shell=WINDOWS)
        if done.returncode != 0:
            say("the interface build failed. The terminal version still works: "
                "`--cli PCSK9`.")
            return False
    return UI_FILE.exists()


# -- starting it ------------------------------------------------------------


def main(argv: list[str]) -> int:
    arguments = list(argv)

    if "--agents" in arguments:  # add the local model runtime, once
        arguments.remove("--agents")
        python = ensure_runtime()
        if not install_agents(python):
            return 1
        if not arguments:
            return 0

    if "--speech" in arguments:  # add the digest's transcription engine, once
        arguments.remove("--speech")
        python = ensure_runtime()
        if not install_speech(python):
            return 1
        if not arguments:
            return 0

    if "--build" in arguments:  # package the exe; see tools/build_exe.py
        arguments.remove("--build")
        import build_exe

        return build_exe.main(arguments)

    if "--setup" in arguments:  # provision and stop, for a machine being prepared
        arguments.remove("--setup")
        python = ensure_runtime()
        ensure_dependencies(python)
        ensure_frontend()
        say(f"ready. The runtime is {python}")
        return 0

    if "--cli" in arguments:
        # Needs nothing but the standard library, so no pip and no npm.
        arguments.remove("--cli")
        python = ensure_runtime()
        target = [str(python), "-m", "spica.cli", *arguments]
    else:
        python = ensure_runtime()
        if not ensure_dependencies(python):
            return 1
        if not ensure_frontend() and "--dev" not in arguments:
            return 1
        target = [str(python), str(ROOT / "app.py"), *arguments]

    return subprocess.run(target, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

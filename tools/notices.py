"""Write THIRD_PARTY_NOTICES.md: the components of Spica and their terms.

    python tools/notices.py

`tools/build_exe.py` runs it before each build, so the notices always match
the contents of the exe. The optional parts (the local model runtime, the
document readers, DESeq2) are listed only when the runtime has them, which
is exactly when the build bundles them. The licence texts are copied from
the packages, not retyped.

The data sources are listed by hand. No data ships inside the exe, but
reports carry values from them, and most of their licences ask for credit.
`docs/licences.md` records the check of each one.
"""

from __future__ import annotations

import sys
from importlib import metadata, util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "THIRD_PARTY_NOTICES.md"
NODE = ROOT / "frontend" / "node_modules"

sys.path.insert(0, str(ROOT))
from spica.credits import CREDITS  # noqa: E402

#: Always in the exe: the window and its bridge, and the Parquet reader the
#: mirror builder uses for Open Targets.
CORE = ("pywebview", "pythonnet", "clr_loader", "proxy_tools", "bottle", "typing_extensions",
        "pyarrow")
#: In the exe when the runtime has llama-cpp (see build_exe.has_llama).
MODEL = ("llama_cpp_python", "numpy", "jinja2", "MarkupSafe", "diskcache")
#: In the exe when the runtime has the document readers (see build_exe.READERS).
READERS = ("pdfminer.six", "charset-normalizer", "cryptography", "cffi", "pycparser",
           "openpyxl", "et_xmlfile", "python-docx", "python-pptx", "lxml", "XlsxWriter", "Pillow")
#: In the exe when the runtime has the transcription engine (build_exe).
SPEECH = ("pywhispercpp", "miniaudio", "cffi", "pycparser")
#: In the exe when the runtime has PyDESeq2 (build_exe): every distribution a
#: DESeq2 run imports, listed from its package metadata (docs/licences.md).
DESEQ = ("pydeseq2", "numpy", "anndata", "formulaic", "formulaic-contrasts", "interface_meta",
         "h5py", "legacy-api-wrap", "matplotlib", "contourpy", "cycler", "fonttools", "kiwisolver",
         "pyparsing", "python-dateutil", "narwhals", "pandas", "tzdata", "scikit-learn", "joblib",
         "cloudpickle", "threadpoolctl", "scipy", "scverse-misc", "wrapt", "zarr", "donfig",
         "google-crc32c", "msgspec", "numcodecs", "natsort", "pydantic", "pydantic_core",
         "pydantic-settings", "annotated-types", "typing-inspection", "python-dotenv", "PyYAML",
         "psutil", "packaging")
#: The interface, inlined into one HTML file by Vite.
FRONTEND = ("react", "react-dom", "scheduler", "lucide-react", "igv", "tailwindcss",
            "@fontsource/sora", "@fontsource/jetbrains-mono")

DATA_TEMPLATE = """\
## Data sources

No database ships inside Spica. Values are read from a local mirror the
user builds, or fetched from each source's public service, and every
value in a report names its source and version. Reports that are shared
outside the user's organisation should keep those credits.

{credits}

JASPAR and ENCORI are off by default because their terms could not be
confirmed; turning them on is the user's decision.
"""

#: The credits table, from the one the exported reports use.
DATA = DATA_TEMPLATE.replace("{credits}", "\n".join(
    ["| Source | Terms | Credit |", "| --- | --- | --- |"]
    + [f"| {c.name} | {c.terms} | {c.credit} |" for c in CREDITS.values()]))

WEBVIEW2 = """\
Copyright (C) Microsoft Corporation. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
   * The name of Microsoft Corporation, or the names of its contributors
may not be used to endorse or promote products derived from this
software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

PYINSTALLER = """\
The program is packaged with PyInstaller. Its bootloader, which starts the
program, is licensed under the GNU General Public License version 2 or
later with this exception: "you may use this bootloader in a program and
distribute that program under terms of your choice, with no requirements
from this license", so it places no obligation on Spica's own licence.
PyInstaller itself is a build tool and is not part of the program.
"""

LLAMA_CPP = """\
llama-cpp-python embeds llama.cpp and ggml, MIT License,
Copyright (c) 2023-2026 The ggml authors.
"""

WHISPER_CPP = """\
pywhispercpp embeds whisper.cpp and ggml, MIT License,
Copyright (c) 2023-2026 The ggml authors. Speech models are not bundled: the
user downloads one (OpenAI's Whisper weights, MIT License, as converted for
whisper.cpp) from inside the program.
"""

PROXY_TOOLS = """\
proxy_tools is distributed under the MIT License (per its package metadata;
the package ships no licence file).
"""


def installed(name: str) -> bool:
    try:
        metadata.distribution(name)
        return True
    except metadata.PackageNotFoundError:
        return False


def readers_present() -> bool:
    return all(util.find_spec(module) for module in ("pdfminer", "openpyxl", "docx", "pptx"))


def speech_present() -> bool:
    return util.find_spec("_pywhispercpp") is not None and util.find_spec("miniaudio") is not None


def model_present() -> bool:
    return util.find_spec("llama_cpp") is not None


def python_texts(name: str) -> tuple[str, str, list[str]]:
    dist = metadata.distribution(name)
    meta = dist.metadata
    licence = (meta.get("License-Expression") or "").strip()
    if not licence:
        classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                       if c.startswith("License ::")]
        first = (meta.get("License") or "").strip().splitlines()
        licence = ", ".join(classifiers) or (first[0] if first else "see the text below")
    texts = []
    for file in dist.files or []:
        upper = str(file).upper()
        if ".DIST-INFO" in upper and any(key in upper for key in ("LICEN", "COPYING", "NOTICE")):
            try:
                texts.append(Path(file.locate()).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return dist.version, licence, texts


def node_texts(name: str) -> tuple[str, str, list[str]]:
    import json

    folder = NODE / name
    package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    texts = [path.read_text(encoding="utf-8", errors="replace")
             for path in sorted(folder.iterdir())
             if path.is_file() and path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING"))]
    return package.get("version", ""), str(package.get("license", "")), texts


def block(name: str, version: str, licence: str, texts: list[str], extra: str = "") -> str:
    lines = [f"### {name} {version}".rstrip(), "", f"Licence: {licence}", ""]
    if extra:
        lines += [extra.rstrip(), ""]
    for text in texts:
        lines += ["```text", text.strip().replace("```", "'''"), "```", ""]
    return "\n".join(lines)


def generate() -> str:
    parts = [
        "# Third-party notices",
        "",
        "Spica is licensed under the PolyForm Strict License 1.0.0 (see LICENSE).",
        "It is built with the open-source components below, each under its own",
        "licence, which LICENSE does not restrict.",
        "This file is generated by `tools/notices.py` from the build itself.",
        "",
        DATA,
        "## Software in the program",
        "",
        "### Python",
        "",
        f"Licence: PSF License Agreement (Python {sys.version.split()[0]})",
        "",
    ]
    python_licence = Path(sys.base_prefix) / "LICENSE.txt"
    if python_licence.exists():
        parts += ["```text", python_licence.read_text(encoding="utf-8", errors="replace").strip(),
                  "```", ""]
    else:
        parts += ["The text is at https://docs.python.org/3/license.html", ""]
    parts += [block("PyInstaller bootloader", "", "GPL-2.0-or-later WITH Bootloader-exception",
                    [], PYINSTALLER)]

    names = list(CORE)
    if model_present():
        names += MODEL
    if readers_present():
        names += READERS
    if speech_present():
        names += [name for name in SPEECH if name not in names]
    if util.find_spec("pydeseq2") is not None:
        names += [name for name in DESEQ if name not in names]
    for name in names:
        if not installed(name):
            continue
        version, licence, texts = python_texts(name)
        extra = (LLAMA_CPP if name == "llama_cpp_python" else PROXY_TOOLS if name == "proxy_tools"
                 else WHISPER_CPP if name == "pywhispercpp" else "")
        parts.append(block(name, version, licence, texts, extra))
        if name == "pywebview":
            parts.append(block("Microsoft WebView2 SDK (bundled with pywebview)", "",
                               "BSD-3-Clause", [WEBVIEW2]))

    parts += ["## The interface", ""]
    for name in FRONTEND:
        if (NODE / name / "package.json").exists():
            parts.append(block(name, *node_texts(name)))
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    OUT.write_text(generate(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The part of the GGUF header needed to size a model before loading it.

The number of layers on the GPU must be correct before the file opens.
With too few, a 22 GB model runs fully on the CPU. With too many, llama.cpp
runs out of VRAM and stops the process. The first kilobytes of the file
hold the answer: the layer count and the tensor sizes are metadata.

This module thus reads the header only, a few KB at the start of the file,
whatever the file size. The format is the documented one: magic, version,
counts, then typed key/value pairs. When parsing fails, the result is None.
The caller then makes a conservative guess; it is not an error.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, BinaryIO

MAGIC = b"GGUF"

# Scalar value types, by the format's own numbering. Arrays (9) and strings
# (8) are skipped rather than read: nothing here needs them.
SCALARS = {
    0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2),
    4: ("I", 4), 5: ("i", 4), 6: ("f", 4), 7: ("?", 1),
    10: ("Q", 8), 11: ("q", 8), 12: ("d", 8),
}
STRING, ARRAY = 8, 9

MAX_KEYS = 2000  # a header with more keys is rejected as malformed


def _read(handle: BinaryIO, fmt: str) -> Any:
    size = struct.calcsize(fmt)
    data = handle.read(size)
    if len(data) < size:
        raise EOFError
    return struct.unpack("<" + fmt, data)[0]


def _skip_string(handle: BinaryIO) -> bytes:
    length = _read(handle, "Q")
    if length > 1 << 20:  # a key or value that large is a parse gone wrong
        raise ValueError("implausible string length")
    return handle.read(length)


def _skip_value(handle: BinaryIO, kind: int) -> Any:
    if kind in SCALARS:
        fmt, _ = SCALARS[kind]
        return _read(handle, fmt)
    if kind == STRING:
        return _skip_string(handle).decode("utf-8", "replace")
    if kind == ARRAY:
        element = _read(handle, "I")
        count = _read(handle, "Q")
        for _ in range(count):
            _skip_value(handle, element)
        return None
    raise ValueError(f"unknown value type {kind}")


def header(path: Path) -> dict[str, Any]:
    """The metadata key/values from a GGUF file, or {} if it cannot be read."""
    try:
        with open(path, "rb") as handle:
            if handle.read(4) != MAGIC:
                return {}
            _read(handle, "I")  # version
            _read(handle, "Q")  # tensor count
            count = _read(handle, "Q")
            if count > MAX_KEYS:
                return {}

            values: dict[str, Any] = {}
            for _ in range(count):
                key = _skip_string(handle).decode("utf-8", "replace")
                value = _skip_value(handle, _read(handle, "I"))
                if value is not None:
                    values[key] = value
            return values
    except (OSError, EOFError, ValueError, struct.error):
        return {}


def block_count(path: Path) -> int | None:
    """How many transformer layers the model has, if the header says."""
    values = header(path)
    architecture = values.get("general.architecture")
    if architecture:
        layers = values.get(f"{architecture}.block_count")
        if isinstance(layers, int) and layers > 0:
            return layers
    for key, value in values.items():
        if key.endswith(".block_count") and isinstance(value, int) and value > 0:
            return value
    return None


def describe(path: Path) -> dict[str, Any]:
    """What the menu shows about a model without loading it."""
    values = header(path)
    architecture = values.get("general.architecture", "")
    layers = block_count(path)
    return {
        "architecture": str(architecture),
        "layers": layers or 0,
        "name": str(values.get("general.name", "") or path.stem),
    }

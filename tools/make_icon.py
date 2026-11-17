"""Draw the Spica mark into `assets/spica.ico`, the icon of the exe.

    python tools/make_icon.py

The art direction specifies the star alone as the app icon. The shape
exists once, as the SVG path in `frontend/src/components/SpicaLogo.tsx`.
This reads that path from the component and keeps no second copy, so the
icon cannot drift away from the logo in the interface.

It uses only the standard library: a small rasterizer, zlib for the PNGs,
and the ICO container around them. No image library to install, and no
manual redraw when the mark changes.
"""

from __future__ import annotations

import math
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "frontend" / "src" / "components" / "SpicaLogo.tsx"
TARGET = ROOT / "assets" / "spica.ico"

VIEWBOX = 32.0  # the mark's own coordinate system
SIZES = (16, 32, 48, 64, 128, 256)
SUBSAMPLES = 4  # sampled rows per pixel row; x coverage is computed exactly

AZURE = (0x00, 0xB2, 0xFF)
WHITE = (0xFF, 0xFF, 0xFF)

# The nucleus, as the component defines it: a Gaussian falloff centred in
# the star's body, clipped to the star so the white never spills outside.
CORE = (11.0, 16.0, 4.2)
FALLOFF = 4.5


# -- the shape --------------------------------------------------------------


def read_mark_path() -> str:
    """The MARK_STAR path data out of the logo component."""
    source = LOGO.read_text(encoding="utf-8")
    match = re.search(r'MARK_STAR\s*=\s*\n?\s*"([^"]+)"', source)
    if not match:
        raise SystemExit(f"[spica] no MARK_STAR path found in {LOGO}")
    return match.group(1)


def parse_path(data: str) -> list[tuple[float, float]]:
    """Flatten an absolute M/L/C/Z path into one polygon.

    Only the three commands the mark uses are handled, and only in their
    absolute form. Anything else is refused loudly rather than drawn wrong.
    """
    tokens = re.findall(r"[MLCZmlcz]|-?\d*\.?\d+", data)
    points: list[tuple[float, float]] = []
    index = 0
    current = (0.0, 0.0)
    start = (0.0, 0.0)

    def number() -> float:
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    while index < len(tokens):
        command = tokens[index]
        if command not in "MLCZmlcz":
            raise SystemExit(f"[spica] unexpected path token {command!r}")
        index += 1
        if command in "Zz":
            current = start
            continue
        if command in "Mm":
            current = (number(), number())
            start = current
            points.append(current)
            continue
        if command in "Ll":
            current = (number(), number())
            points.append(current)
            continue
        # Cubic: flatten into segments, finely enough that 256 px hides it.
        control1 = (number(), number())
        control2 = (number(), number())
        end = (number(), number())
        points.extend(flatten_cubic(current, control1, control2, end))
        current = end
    return points


def flatten_cubic(p0, p1, p2, p3, steps: int = 24) -> list[tuple[float, float]]:
    out = []
    for step in range(1, steps + 1):
        t = step / steps
        u = 1 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
        out.append((x, y))
    return out


# -- rasterizing ------------------------------------------------------------


def coverage(polygon: list[tuple[float, float]], size: int) -> list[list[float]]:
    """How much of each pixel the shape covers, 0 to 1.

    Scanline fill: exact where the edges cross in x, sampled in y. That is
    where the eye notices the difference on a diagonal ray like this one.
    """
    scale = size / VIEWBOX
    points = [(x * scale, y * scale) for x, y in polygon]
    edges = [
        (points[i], points[(i + 1) % len(points)])
        for i in range(len(points))
        if points[i] != points[(i + 1) % len(points)]
    ]

    grid = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for sub in range(SUBSAMPLES):
            y = row + (sub + 0.5) / SUBSAMPLES
            crossings = []
            for (x0, y0), (x1, y1) in edges:
                if (y0 <= y < y1) or (y1 <= y < y0):
                    x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                    crossings.append((x, 1 if y1 > y0 else -1))
            if not crossings:
                continue
            crossings.sort()

            winding = 0
            span_start = 0.0
            for x, direction in crossings:
                if winding != 0:
                    add_span(grid[row], span_start, x, size)
                winding += direction
                if winding != 0 and winding - direction == 0:
                    span_start = x
    return [[min(1.0, value / SUBSAMPLES) for value in row] for row in grid]


def add_span(row: list[float], start: float, end: float, size: int) -> None:
    """Add one filled run to a row, with the ends counted fractionally."""
    if end <= start:
        return
    first = max(0, int(math.floor(start)))
    last = min(size - 1, int(math.ceil(end)) - 1)
    for pixel in range(first, last + 1):
        overlap = min(end, pixel + 1) - max(start, pixel)
        if overlap > 0:
            row[pixel] += overlap


def render(polygon: list[tuple[float, float]], size: int) -> bytes:
    """RGBA bytes for one icon size."""
    alpha = coverage(polygon, size)
    scale = size / VIEWBOX
    cx, cy, radius = (value * scale for value in CORE)

    out = bytearray()
    for y in range(size):
        for x in range(size):
            a = alpha[y][x]
            if a <= 0:
                out.extend((0, 0, 0, 0))
                continue
            distance = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            glow = math.exp(-FALLOFF * (distance / radius) ** 2) if distance < radius else 0.0
            pixel = tuple(
                round(azure * (1 - glow) + white * glow)
                for azure, white in zip(AZURE, WHITE)
            )
            out.extend((*pixel, round(a * 255)))
    return bytes(out)


# -- the files --------------------------------------------------------------


def png(rgba: bytes, size: int) -> bytes:
    raw = bytearray()
    stride = size * 4
    for row in range(size):
        raw.append(0)  # filter: none
        raw.extend(rgba[row * stride:(row + 1) * stride])

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def ico(images: list[tuple[int, bytes]]) -> bytes:
    """An ICO holding PNGs, which Windows has read since Vista."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = bytearray(), bytearray()
    for size, blob in images:
        entries.extend(struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,  # 0 means 256
            0 if size >= 256 else size,
            0, 0, 1, 32, len(blob), offset,
        ))
        blobs.extend(blob)
        offset += len(blob)
    return header + bytes(entries) + bytes(blobs)


def main() -> int:
    polygon = parse_path(read_mark_path())
    images = [(size, png(render(polygon, size), size)) for size in SIZES]
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(ico(images))
    print(f"[spica] wrote {TARGET} ({TARGET.stat().st_size // 1024} KB, "
          f"{', '.join(str(size) for size in SIZES)} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

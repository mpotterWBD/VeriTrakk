"""The logo (assets/logo_with_circle_nowords.svg) drawn in text, for the home
screen's left panel (Mike, 2026-11-16: in place of the matrix rain).

Each character is a Braille pattern, a 2 x 4 grid of dots, the finest a
terminal can draw; a character cell is about twice as tall as it's wide, so a
dot is near enough square. The SVG's filled paths are flattened to polygons
and filled scan line by scan line with the nonzero rule (as SVG fills them),
sampling each dot at its middle.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_CURVE_STEPS = 8   # straight pieces per Bezier curve

SUB = 4                 # each dot sampled SUB x SUB times...
COVER = 5 / 16          # ...and lit when the logo covers this much of it
SMALL_DOTS = 64         # drawn narrower than this many dots, the SMALL_HIDE parts are left out
SMALL_HIDE = {2, 3}     # the logo's two inner arrows (its 3rd and 4th <path>s): too fine to show small

# Braille dot bits by (column, row) in a cell: the Unicode layout.
_DOT_BITS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (1, 0): 0x08,
             (1, 1): 0x10, (1, 2): 0x20, (0, 3): 0x40, (1, 3): 0x80}


Point = tuple[float, float]


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point) -> list[Point]:
    out = []
    for k in range(1, _CURVE_STEPS + 1):
        t = k / _CURVE_STEPS
        u = 1.0 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def path_polygons(d: str) -> list[list[Point]]:
    """An SVG path's `d` as closed polygons (one per subpath): M L H V C S Z,
    absolute and relative (what the logo uses)."""
    polys: list[list[Point]] = []
    cur: list[Point] = []
    x = y = 0.0
    last_ctrl: Point | None = None
    for cmd, args in re.findall(r"([MmLlHhVvCcSsZz])([^MmLlHhVvCcSsZz]*)", d):
        nums = [float(n) for n in _NUMBER.findall(args)]
        rel = cmd.islower()
        c = cmd.upper()
        if c == "Z":
            if cur:
                polys.append(cur)
                x, y = cur[0]
            cur = []
            last_ctrl = None
            continue
        if c in "MLHV":
            step = 1 if c in "HV" else 2
            for k in range(0, len(nums), step):
                if c == "H":
                    x = nums[k] + (x if rel else 0.0)
                elif c == "V":
                    y = nums[k] + (y if rel else 0.0)
                else:
                    x, y = (x + nums[k], y + nums[k + 1]) if rel else (nums[k], nums[k + 1])
                if c == "M" and k == 0:
                    if cur:
                        polys.append(cur)
                    cur = [(x, y)]
                else:
                    cur.append((x, y))
            last_ctrl = None
            continue
        step = 6 if c == "C" else 4
        for k in range(0, len(nums), step):
            ox, oy = (x, y) if rel else (0.0, 0.0)
            if c == "C":
                x1, y1, x2, y2, ex, ey = nums[k:k + 6]
                x1, y1 = x1 + ox, y1 + oy
            else:   # S: the first control point mirrors the last one
                x2, y2, ex, ey = nums[k:k + 4]
                x1, y1 = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl else (x, y)
            x2, y2, ex, ey = x2 + ox, y2 + oy, ex + ox, ey + oy
            cur += _bezier((x, y), (x1, y1), (x2, y2), (ex, ey))
            last_ctrl = (x2, y2)
            x, y = ex, ey
    if cur:
        polys.append(cur)
    return polys


class Logo:
    """The logo read from its SVG: its view box, color, and each path's polygons."""

    def __init__(self, svg: str) -> None:
        box = re.search(r'viewBox="\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)\s*"', svg)
        if not box:
            raise ValueError("no viewBox")
        self.x, self.y, self.w, self.h = (float(v) for v in box.groups())
        color = re.search(r"fill:\s*(#[0-9a-fA-F]{6})", svg)
        self.color = color.group(1) if color else "#ffffff"
        self.paths = [path_polygons(d) for d in re.findall(r'<path[^>]*\sd="([^"]+)"', svg)]

    @classmethod
    def load(cls, path: Path) -> "Logo | None":
        try:
            return cls(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _row_spans(self, y: float, paths: list[list[list[Point]]] | None = None) -> list[tuple[float, float]]:
        """Where the scan line at `y` (logo units) is inside the logo: [x0, x1)
        spans, each path filled by the nonzero rule."""
        spans: list[tuple[float, float]] = []
        for polys in self.paths if paths is None else paths:
            hits: list[tuple[float, int]] = []
            for poly in polys:
                for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
                    if (ay <= y < by) or (by <= y < ay):
                        hits.append((ax + (y - ay) * (bx - ax) / (by - ay), 1 if by > ay else -1))
            hits.sort()
            winding = 0
            for k, (hx, dirn) in enumerate(hits):
                winding += dirn
                if winding != 0 and k + 1 < len(hits):
                    spans.append((hx, hits[k + 1][0]))
        return spans

    def braille(self, cols: int, rows: int, corner: bool = False) -> list[str]:
        """The logo in Braille, as large as fits `cols` x `rows` characters
        (keeping its shape), centred, or with `corner` in the top-left corner;
        one string per row, `cols` wide.

        Each dot is sampled SUB x SUB times and lit when the logo covers at least
        COVER of it, so edges come out even rather than ragged. Drawn small (under
        SMALL_DOTS across), the SMALL_HIDE parts are left out (Mike, 2026-11-16:
        at that size they only blurred into the rest)."""
        if cols <= 0 or rows <= 0:
            return []
        # A dot is half a cell wide and a quarter of one tall; cells are ~1:2, so dots ~square.
        scale = min(cols * 2 / self.w, rows * 4 / self.h)
        # Rounded, not cut down (Mike, 2026-11-16: 95.99 dots cut to 95 lost the ring's
        # right edge), and never more than there's room for.
        dots_w = min(cols * 2, round(self.w * scale))
        dots_h = min(rows * 4, round(self.h * scale))
        off_x = 0 if corner else (cols * 2 - dots_w) // 2
        off_y = 0 if corner else (rows * 4 - dots_h) // 2
        paths = self.paths
        if dots_w < SMALL_DOTS:
            paths = [p for k, p in enumerate(self.paths) if k not in SMALL_HIDE]
        n = dots_w * SUB   # samples across a row
        need = COVER * SUB * SUB
        cells = [[0] * cols for _ in range(rows)]
        for dy in range(dots_h):
            counts = [0] * dots_w
            for k in range(SUB):
                spans = self._row_spans(self.y + (dy + (k + 0.5) / SUB) / scale, paths)
                inside = bytearray(n)
                for a, b in spans:
                    # samples sit at x + (i + 0.5) / (SUB * scale): those in [a, b)
                    i0 = max(0, math.ceil((a - self.x) * scale * SUB - 0.5))
                    i1 = min(n, math.ceil((b - self.x) * scale * SUB - 0.5))
                    for i in range(i0, i1):
                        inside[i] = 1
                for dx in range(dots_w):
                    counts[dx] += sum(inside[dx * SUB:(dx + 1) * SUB])
            for dx in range(dots_w):
                if counts[dx] >= need:
                    px, py = dx + off_x, dy + off_y
                    if 0 <= px < cols * 2 and 0 <= py < rows * 4:
                        cells[py // 4][px // 2] |= _DOT_BITS[(px % 2, py % 4)]
        return ["".join(chr(0x2800 + bits) if bits else " " for bits in row) for row in cells]

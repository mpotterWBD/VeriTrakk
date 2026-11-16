"""The logo (assets/logo_with_circle_nowords.svg) drawn in text, for the home
screen's left panel (Mike, 2026-11-16: in place of the matrix rain).

Each character is a Braille pattern, a 2 x 4 grid of dots, the finest a
terminal can draw; a character cell is about twice as tall as it's wide, so a
dot is near enough square. The SVG's filled paths are flattened to polygons
and filled scan line by scan line with the nonzero rule (as SVG fills them),
sampling each dot at its middle.
"""
from __future__ import annotations

import re
from pathlib import Path

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_CURVE_STEPS = 8   # straight pieces per Bezier curve

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

    def _row_spans(self, y: float) -> list[tuple[float, float]]:
        """Where the scan line at `y` (logo units) is inside the logo: [x0, x1)
        spans, each path filled by the nonzero rule."""
        spans: list[tuple[float, float]] = []
        for polys in self.paths:
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

    def braille(self, cols: int, rows: int) -> list[str]:
        """The logo in Braille, as large as fits `cols` x `rows` characters
        (keeping its shape), centred; one string per row, `cols` wide."""
        if cols <= 0 or rows <= 0:
            return []
        # A dot is half a cell wide and a quarter of one tall; cells are ~1:2, so dots ~square.
        scale = min(cols * 2 / self.w, rows * 4 / self.h)
        dots_w, dots_h = int(self.w * scale), int(self.h * scale)
        off_x = (cols * 2 - dots_w) // 2
        off_y = (rows * 4 - dots_h) // 2
        cells = [[0] * cols for _ in range(rows)]
        for dy in range(dots_h):
            spans = self._row_spans(self.y + (dy + 0.5) / scale)
            if not spans:
                continue
            for dx in range(dots_w):
                lx = self.x + (dx + 0.5) / scale
                if any(a <= lx < b for a, b in spans):
                    px, py = dx + off_x, dy + off_y
                    if 0 <= px < cols * 2 and 0 <= py < rows * 4:
                        cells[py // 4][px // 2] |= _DOT_BITS[(px % 2, py % 4)]
        return ["".join(chr(0x2800 + bits) if bits else " " for bits in row) for row in cells]

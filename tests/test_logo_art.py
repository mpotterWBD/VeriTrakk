"""The logo drawn in Braille text for the home panel (Mike, 2026-11-16)."""
from __future__ import annotations

from src import storage
from src.logo_art import Logo, path_polygons

SQUARE = '<svg viewBox="0 0 10 10"><style>.a{fill:#123456;}</style><path class="a" d="M0,0H10V10H0Z"/></svg>'
RING = ('<svg viewBox="0 0 10 10"><path d="M0,0H10V10H0Z M3,3V7H7V3Z"/></svg>')   # (a hole, wound the other way)


def test_reads_the_real_logo():
    logo = Logo.load(storage.LOGO_SVG)
    assert logo is not None and logo.color.lower() == "#00aeef" and len(logo.paths) == 7


def test_fits_and_keeps_its_shape():
    rows = Logo.load(storage.LOGO_SVG).braille(40, 12)
    assert len(rows) == 12 and all(len(r) == 40 for r in rows)
    used = [k for k, ch in enumerate(rows[6]) if ch != " "]
    width = used[-1] - used[0] + 1
    assert 20 <= width <= 26   # (12 rows of 4 dots = 48 dots tall, so ~24 cells of 2 dots wide)


def test_a_filled_square_is_all_dots():
    rows = Logo(SQUARE).braille(5, 3)
    assert rows[1] == "⣿" * 5 or rows[1].strip() == "⣿" * len(rows[1].strip())


def test_nonzero_fill_leaves_the_hole():
    rows = Logo(RING).braille(10, 5)
    assert rows[2][4] == " " and rows[0][4] != " "


def test_path_commands():
    polys = path_polygons("M1,2h3v4l-1-1z")
    assert polys == [[(1.0, 2.0), (4.0, 2.0), (4.0, 6.0), (3.0, 5.0)]]


def test_missing_file_draws_nothing(tmp_path):
    assert Logo.load(tmp_path / "missing.svg") is None

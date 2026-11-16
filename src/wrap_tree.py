"""A Textual Tree whose node labels word-wrap to the widget width.

Textual's Tree draws every node on exactly one row and scrolls sideways when a
label is wider than the widget, so long step labels get clipped. WrapTree keeps
Tree's public model (one "line" per visible node: cursor_line, hover_line,
get_node_at_line, NodeSelected, ...) and adds a row layout on top: each line
takes as many screen rows as its label needs at the current width. The layout
is rebuilt whenever the tree is rebuilt, the widget is resized, or a label's
text changes, so wrapping follows the window width live.
"""

from __future__ import annotations

import re

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual._segment_tools import line_pad
from textual.geometry import Region, Size
from textual.strip import Strip
from textual.widgets import Tree

# Continuation rows are indented past a leading status icon ("○  ", "✓  ")
# and an outline number ("1.2 "), so wrapped text lines up with the label text.
_HANG_RE = re.compile(r"^\s*(?:[^\w\s\[\(!]{1,2}\s+)?(?:\d+(?:\.\d+)*\.?\s+)?")


def _wrap_spans(plain: str, first_width: int, rest_width: int) -> list[tuple[int, int]]:
    """Greedy word wrap by terminal cells. Returns (start, end) spans of `plain`."""
    spans: list[tuple[int, int]] = []
    n = len(plain)
    start = 0
    width = max(1, first_width)
    while start < n:
        used = 0
        i = start
        last_space = -1
        while i < n:
            cw = cell_len(plain[i])
            if used + cw > width:
                break
            if plain[i] == " ":
                last_space = i
            used += cw
            i += 1
        if i >= n:
            spans.append((start, n))
            break
        if plain[i] == " ":
            end = i
        elif last_space > start:
            end = last_space
        else:
            end = max(i, start + 1)  # one word longer than the row: hard split
        spans.append((start, end))
        start = end
        while start < n and plain[start] == " ":
            start += 1
        width = max(1, rest_width)
    return spans or [(0, 0)]


class WrapTree(Tree):
    """Tree whose node labels wrap onto extra rows instead of being clipped."""

    def __init__(self, *args, **kwargs) -> None:
        self._build_gen = 0
        self._rows_key: tuple | None = None
        self._line_spans: list[list[tuple[int, int]]] = []
        self._line_hangs: list[int] = []
        self._line_row_start: list[int] = []
        self._row_owner: list[tuple[int, int]] = []
        super().__init__(*args, **kwargs)

    # ── row layout ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_gen += 1
        super()._build()
        self._ensure_rows()

    def _ensure_rows(self) -> bool:
        """Recompute the row layout if anything it depends on changed.

        Returns True when the number of rows of any line changed.
        """
        lines = self._tree_lines
        width = max(1, self.size.width)
        key = (
            self._build_gen,
            width,
            self.guide_depth,
            self.show_root,
            tuple(line.node._label.plain for line in lines),
        )
        if key == self._rows_key:
            return False
        self._rows_key = key

        old_counts = [len(s) for s in self._line_spans]
        spans_all: list[list[tuple[int, int]]] = []
        hangs: list[int] = []
        row_start: list[int] = []
        owner: list[tuple[int, int]] = []
        for idx, line in enumerate(lines):
            guide_w = line._get_guide_width(self.guide_depth, self.show_root)
            avail = max(1, width - guide_w)
            plain = self.render_label(line.node, Style(), Style()).plain
            toggle_w = 2 if line.node._allow_expand else 0
            match = _HANG_RE.match(plain[toggle_w:])
            hang = toggle_w + (cell_len(match.group(0)) if match else 0)
            hang = min(hang, avail // 2)
            spans = _wrap_spans(plain, avail, avail - hang)
            spans_all.append(spans)
            hangs.append(hang)
            row_start.append(len(owner))
            owner.extend((idx, sub) for sub in range(len(spans)))

        self._line_spans = spans_all
        self._line_hangs = hangs
        self._line_row_start = row_start
        self._row_owner = owner
        self._line_cache.clear()
        self.virtual_size = Size(width, len(owner))
        changed = old_counts != [len(s) for s in spans_all]
        if changed:
            self.refresh()
        return changed

    def _rows_of(self, line: int) -> tuple[int, int]:
        """(first row, row count) for a tree line."""
        if 0 <= line < len(self._line_row_start):
            return self._line_row_start[line], len(self._line_spans[line])
        return line, 1

    # ── Tree hooks that assume one row per line ──────────────────────────────

    def _get_label_region(self, line: int) -> Region | None:
        try:
            tree_line = self._tree_lines[line]
        except IndexError:
            return None
        self._ensure_rows()
        x = tree_line._get_guide_width(self.guide_depth, self.show_root)
        row, count = self._rows_of(line)
        return Region(x, row, max(1, self.size.width - x), count)

    def _refresh_line(self, line: int) -> None:
        row, count = self._rows_of(line)
        self.refresh(Region(0, row - self.scroll_offset.y, self.size.width, count))

    def _refresh_node(self, node) -> None:
        if self._ensure_rows():
            return  # full refresh already queued
        top = self.scroll_offset.y
        bottom = top + self.size.height
        for line_no, line in enumerate(self._tree_lines):
            if node not in line.path:
                continue
            row, count = self._rows_of(line_no)
            if row + count > top and row < bottom:
                self._refresh_line(line_no)

    def render_lines(self, crop: Region) -> list[Strip]:
        self._ensure_rows()
        return super().render_lines(crop)

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        row = y + self.scroll_offset.y
        if row < 0 or row >= len(self._row_owner):
            return Strip.blank(width, self.rich_style)
        idx, sub = self._row_owner[row]
        return self._render_rows(idx, self.rich_style)[sub].crop(0, width)

    # ── drawing ─────────────────────────────────────────────────────────────

    def _render_rows(self, y: int, base_style: Style) -> list[Strip]:
        line = self._tree_lines[y]
        width = self.size.width
        is_hover = self.hover_line >= 0 and any(node._hover for node in line.path)
        cache_key = (
            "wrap",
            y,
            is_hover,
            width,
            self._updates,
            self._pseudo_class_state,
            tuple(node._updates for node in line.path),
            tuple(self._line_spans[y]),
        )
        cached = self._line_cache.get(cache_key)
        if cached is not None:
            return cached

        base_hidden = self.get_component_styles("tree--guides").color.a == 0
        hover_hidden = self.get_component_styles("tree--guides-hover").color.a == 0
        selected_hidden = self.get_component_styles("tree--guides-selected").color.a == 0
        base_guide_style = self.get_component_rich_style("tree--guides", partial=True)
        guide_hover_style = base_guide_style + self.get_component_rich_style(
            "tree--guides-hover", partial=True
        )
        guide_selected_style = base_guide_style + self.get_component_rich_style(
            "tree--guides-selected", partial=True
        )

        hover = line.path[0]._hover
        selected = line.path[0]._selected and self.has_focus

        def get_guides(style: Style, hidden: bool) -> tuple[str, str, str, str]:
            if self.show_guides and not hidden:
                chars = self.LINES["default"]
                if style.bold:
                    chars = self.LINES["bold"]
                elif style.underline2:
                    chars = self.LINES["double"]
            else:
                chars = ("  ", "  ", "  ", "  ")
            depth = max(0, self.guide_depth - 2)
            return tuple(f"{c[0]}{c[1] * depth} " for c in chars)  # type: ignore[return-value]

        line_style = (
            self.get_component_rich_style("tree--highlight-line") if is_hover else base_style
        )
        line_style += Style(meta={"line": y})

        guides = Text(style=line_style)       # first row
        cont_guides = Text(style=line_style)  # wrapped rows
        guide_style = base_guide_style
        hidden = True
        for node in line.path[1:]:
            hidden = base_hidden
            if hover:
                guide_style = guide_hover_style
                hidden = hover_hidden
            if selected:
                guide_style = guide_selected_style
                hidden = selected_hidden
            space, vertical, _, _ = get_guides(guide_style, hidden)
            guide = space if node.is_last else vertical
            if node != line.path[-1]:
                guides.append(guide, style=guide_style)
                cont_guides.append(guide, style=guide_style)
            hover = hover or node._hover
            selected = (selected or node._selected) and self.has_focus

        if len(line.path) > 1:
            space, vertical, terminator, cross = get_guides(guide_style, hidden)
            guides.append(terminator if line.last else cross, style=guide_style)
            cont_guides.append(space if line.last else vertical, style=guide_style)

        label_style = self.get_component_rich_style("tree--label", partial=True)
        if self.hover_line == y:
            label_style += self.get_component_rich_style("tree--highlight", partial=True)
        if self.cursor_line == y:
            label_style += self.get_component_rich_style("tree--cursor", partial=False)

        label = self.render_label(line.path[-1], line_style, label_style).copy()
        label.stylize(Style(meta={"node": line.node._id}))

        # Children hang off the label column; keep their guide joined through
        # the wrapped rows of an expanded parent.
        node = line.node
        child_bar = node.is_expanded and bool(node._children) and self.show_guides
        _, bar, _, _ = get_guides(guide_style, base_hidden)

        hang = self._line_hangs[y]
        strips: list[Strip] = []
        for sub, (start, end) in enumerate(self._line_spans[y]):
            piece = label[start:end]
            if sub == 0:
                row_text = guides.copy()
            else:
                row_text = cont_guides.copy()
                if hang:
                    lead = bar[0] if child_bar else " "
                    row_text.append(lead, style=guide_style)
                    row_text.append(" " * (hang - 1), style=line_style)
            row_text.append(piece)
            segments = list(row_text.render(self.app.console))
            segments = line_pad(segments, 0, max(0, width - row_text.cell_len), line_style)
            strips.append(Strip(segments))

        self._line_cache[cache_key] = strips
        return strips

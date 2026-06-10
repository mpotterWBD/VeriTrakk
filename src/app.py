"""
VeriTrakk  -  app.py
Full rewrite with clean split-layout UI, modal screens for editing,
toolbar-driven navigation, and CSV-backed data model.
"""
from __future__ import annotations

import copy
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, ContentSwitcher, DirectoryTree, Footer, Header,
    Digits, Input, Label, Log, Markdown, Static, Switch, Tree,
)

from .storage import (
    DATA_DIR, LOGS_DIR, Process, Step,
    load_process, save_process,
    load_session, save_session,
    sanitize_filename_for,
    generate_log_text, publish_process,
    create_process_instance,
)

# Brand colors as hex (Rich doesn't know Textual CSS color names)
_SALMON  = "#ffa07a"  # lightsalmon
_GREEN   = "#8fbc8f"  # darkseagreen
_GOLD    = "#daa520"  # goldenrod
_KHAKI   = "#bdb76b"  # darkkhaki
_TEAL    = "#5f9ea0"  # cadetblue
_BLUE    = "#1e90ff"  # dodgerblue
_PURPLE  = "#9370db"  # mediumpurple


# ── Home matrix rain knobs ───────────────────────────────────────────────────
# Pick exactly 3 characters for the standard random rain.
MATRIX_RAIN_RANDOM_CHARS = "01#"
# Words that occasionally fall vertically in the rain.
MATRIX_RAIN_SNEAKY_WORDS = ["VERITRAKK", "WESTBOUND", "QUALITY", "DESIGNS"]
# Density knob (0.0-1.0): higher values create more falling characters.
MATRIX_RAIN_DENSITY = 0.24
MATRIX_RAIN_CHAR_SPAWN_CHANCE = 0.55
MATRIX_RAIN_SNEAKY_WORD_CHANCE = 0.06
# Max number of matrix columns. Set to 0 to auto-fit full panel width.
MATRIX_RAIN_WIDTH = 0
MATRIX_RAIN_TOP_ROWS = 10
MATRIX_RAIN_BOTTOM_ROWS = 10
MATRIX_RAIN_TICK_SECONDS = 0.01
MATRIX_RAIN_COLOR = "#1e90ff"
MATRIX_RAIN_SNEAKY_WORD_COLOR = "#ffa07a"
MATRIX_RAIN_COLUMN_MIN_INTERVAL_TICKS = 1
MATRIX_RAIN_COLUMN_MAX_INTERVAL_TICKS = 6
MATRIX_RAIN_COLUMN_CHAR_CHANGE_CYCLES = 3


# ── Welcome content ───────────────────────────────────────────────────────────

WELCOME_MD = """\
# VeriTrakk

**Process tracking, built for the floor.**

---

## Quick Start

1. **New** - Create a new process checklist
2. **Open** - Load a `.prcss` process file
3. **Resume** - Jump back into your last active process
4. **Build** - Edit or create a process checklist
5. **Logs** - Archive completed processes and review history

---

## Running a Process

| Key | Action |
|-----|--------|
| Arrow Up / Down | Navigate tasks |
| Arrow Right | Mark task **complete** |
| Arrow Left | Un-mark a task |
| N | Add / edit a **note** on the selected task |
| P | Pause / unpause active task |

## Process Builder

| Key | Action |
|-----|--------|
| A | Add a new top-level task |
| S | Add a sub task under current task |
| E | Edit selected task label / thresholds |
| D | Delete selected task |
| Ctrl+S | Save process |

---

*Westbound Designs*
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _progress_bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _step_label(
    step: Step,
    *,
    number_prefix: str = "",
    show_process_badge: bool = False,
    sub_done: int | None = None,
    sub_total: int | None = None,
    live_seconds: int | None = None,
) -> Text:
    """Rich Text label for a step node in the run-mode tree."""
    display_label = f"{number_prefix} {step.label}" if number_prefix else step.label
    if step.main_quest:
        display_label = f"!!! {display_label} !!!"
    if show_process_badge and step.linked_process_path.strip():
        display_label = f"[P] {display_label}"
    if step.completed:
        if step.result == "PASS":
            t = Text(f"\u2713  {display_label}", style=f"bold {_GREEN}")
            t.append("   PASS", style=f"bold {_GREEN}")
        elif step.result == "FAIL":
            t = Text(f"\u2717  {display_label}", style="bold red")
            t.append("   FAIL", style="bold red")
        else:
            ts = ""
            if step.completed_at:
                try:
                    dt = datetime.fromisoformat(step.completed_at)
                    ts = f"   {dt.strftime('%I:%M %p').lstrip('0')}"
                except ValueError:
                    pass
            t = Text(f"\u2713  {display_label}", style=_GREEN)
            if ts:
                t.append(ts, style=f"dim {_GREEN}")
            if live_seconds is not None and live_seconds > 0:
                h = live_seconds // 3600
                m = (live_seconds % 3600) // 60
                s = live_seconds % 60
                t.append(f"   {h:02d}:{m:02d}:{s:02d}", style=f"dim {_TEAL}")
            elif step.duration_minutes > 0:
                h = step.duration_minutes // 60
                m = step.duration_minutes % 60
                t.append(f"   {h:02d}:{m:02d}", style=f"dim {_TEAL}")
    elif step.started and step.paused:
        t = Text(f"\u25d4  {display_label}", style=f"bold {_PURPLE}")
        t.append("   PAUSED", style=f"bold {_PURPLE}")
        if live_seconds is not None and live_seconds > 0:
            h = live_seconds // 3600
            m = (live_seconds % 3600) // 60
            s = live_seconds % 60
            t.append(f"   {h:02d}:{m:02d}:{s:02d}", style=f"dim {_TEAL}")
        if sub_done is not None and sub_total:
            t.append(f"  ({sub_done}/{sub_total})", style=f"dim {_KHAKI}")
    elif step.started:
        t = Text(f"\u25d4  {display_label}", style=f"bold {_BLUE}")
        if live_seconds is not None and live_seconds > 0:
            h = live_seconds // 3600
            m = (live_seconds % 3600) // 60
            s = live_seconds % 60
            t.append(f"   {h:02d}:{m:02d}:{s:02d}", style=f"dim {_TEAL}")
        if sub_done is not None and sub_total:
            t.append(f"  ({sub_done}/{sub_total})", style=f"dim {_KHAKI}")
    else:
        t = Text(f"\u25cb  {display_label}")
        if live_seconds is not None and live_seconds > 0:
            h = live_seconds // 3600
            m = (live_seconds % 3600) // 60
            s = live_seconds % 60
            t.append(f"   {h:02d}:{m:02d}:{s:02d}", style=f"dim {_TEAL}")
        if sub_done is not None and sub_total:
            t.append(f"  ({sub_done}/{sub_total})", style=f"dim {_KHAKI}")
        if step.has_threshold():
            t.append("  \u2299", style=_TEAL)
        if step.note:
            t.append("  \xb7", style=f"dim {_KHAKI}")
    return t


def _builder_label(step: Step, *, number_prefix: str = "") -> Text:
    """Rich Text label for a step node in the builder tree."""
    prefix = "  " * max(0, step.level - 1)
    label = f"{number_prefix} {step.label}" if number_prefix else step.label
    t = Text(f"{prefix}{label}")
    extras: list[str] = []
    if step.has_threshold():
        extras.append("[T]")
    if step.manual_pass_fail:
        extras.append("[B]")
    if step.requires_text_input:
        extras.append("[I]")
    if step.linked_process_path:
        extras.append("[L]")
    if step.main_quest:
        extras.append("[M]")
    if extras:
        t.append(f"  {'  '.join(extras)}", style=f"dim {_KHAKI}")
    return t


# ── Specialized DirectoryTree subclasses ──────────────────────────────────────

class ProcessFileTree(DirectoryTree):
    """Shows directories and active process/work quest files."""
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            p for p in paths
            if p.is_dir() or (
                p.suffix in (".prcss", ".wrkqst") and "#COMPLETE" not in p.name
            )
        ]


class PrcssFileTree(DirectoryTree):
    """Shows directories and active .prcss files only."""
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            p for p in paths
            if p.is_dir() or (p.suffix == ".prcss" and "#COMPLETE" not in p.name)
        ]


class WorkQuestFileTree(DirectoryTree):
    """Shows directories and active .wrkqst files only."""
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            p for p in paths
            if p.is_dir() or (p.suffix == ".wrkqst" and "#COMPLETE" not in p.name)
        ]


class LogFileTree(DirectoryTree):
    """Shows directories, log files, and #COMPLETE source files."""
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            p for p in paths
            if p.is_dir()
            or p.suffix in (".prcsslog", ".wrkqstlog")
            or (p.suffix in (".prcss", ".wrkqst") and "#COMPLETE" in p.name)
        ]


class DirOnlyTree(DirectoryTree):
    """Shows only directories (for picking a save location)."""
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.is_dir()]


# ── Modal Screens ─────────────────────────────────────────────────────────────

class NoteScreen(ModalScreen):
    """Add/edit multiple timestamped notes with keyboard navigation."""
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "prev_note", "Previous Note", show=False),
        Binding("down", "next_note", "Next Note", show=False),
    ]

    def __init__(self, current_note: str = "") -> None:
        super().__init__()
        self._notes = self._parse_notes(current_note)
        # Cursor points at a note index, or at len(_notes) for the draft slot.
        self._idx = len(self._notes)

    @staticmethod
    def _parse_notes(current_note: str) -> list[tuple[str, str]]:
        notes: list[tuple[str, str]] = []
        for raw in current_note.splitlines():
            line = raw.strip()
            if not line:
                continue
            m = re.match(r"^\[(.*?)\]\s*(.*)$", line)
            if m:
                notes.append((m.group(1).strip(), m.group(2).strip()))
            else:
                # Legacy un-timestamped notes become editable notes.
                notes.append(("", line))
        return notes

    def _serialize_notes(self) -> str:
        out: list[str] = []
        for ts, text in self._notes:
            if not text:
                continue
            stamp = ts or datetime.now().strftime("%Y-%m-%d %H:%M")
            out.append(f"[{stamp}] {text}")
        return "\n".join(out)

    def _input(self) -> Input:
        return self.query_one("#note_inp", Input)

    def _is_draft(self) -> bool:
        return self._idx >= len(self._notes)

    def _load_current_into_input(self) -> None:
        inp = self._input()
        if self._is_draft():
            inp.value = ""
        else:
            inp.value = self._notes[self._idx][1]
        self._refresh_meta()

    def _refresh_meta(self) -> None:
        meta = self.query_one("#note_meta", Static)
        delete_btn = self.query_one("#btn_delete", Button)
        preview = self.query_one("#note_existing", Static)

        if self._is_draft():
            meta.update(f"Draft Note {len(self._notes) + 1} of {len(self._notes) + 1}")
            delete_btn.disabled = True
        else:
            ts, _ = self._notes[self._idx]
            shown_ts = ts or "(will timestamp on save)"
            meta.update(f"Editing Note {self._idx + 1} of {len(self._notes)}  |  {shown_ts}")
            delete_btn.disabled = False

        serialized = self._serialize_notes()
        preview.update(serialized if serialized else "No saved notes yet.")

    def _commit_current(self) -> None:
        text = self._input().value.strip()

        # Draft slot appends a new timestamped note only when text exists.
        if self._is_draft():
            if not text:
                return
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._notes.append((stamp, text))
            self._idx = len(self._notes)
            return

        # Existing note: edit text while preserving timestamp.
        ts, _ = self._notes[self._idx]
        if text:
            self._notes[self._idx] = (ts or datetime.now().strftime("%Y-%m-%d %H:%M"), text)

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_box"):
            yield Static("Step Notes", id="modal_title")
            yield Label("Existing Notes")
            yield Static("", id="note_existing")
            yield Static("", id="note_meta")
            yield Label("Current Note")
            yield Input(placeholder="Add note...", id="note_inp")
            with Horizontal(id="note_nav_btns"):
                yield Button("Up",      variant="default", id="btn_prev")
                yield Button("Down",    variant="success", id="btn_next")
                yield Button("Delete",  variant="error",   id="btn_delete")
            with Horizontal(id="modal_btns"):
                yield Button("Save",    variant="primary", id="btn_save")
                yield Button("Clear",   variant="warning", id="btn_clear")
                yield Button("Cancel",                   id="btn_cancel")

    def on_mount(self) -> None:
        self._load_current_into_input()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_prev_note(self) -> None:
        self._commit_current()
        if self._is_draft() and self._notes:
            self._idx = len(self._notes) - 1
        elif self._idx > 0:
            self._idx -= 1
        self._load_current_into_input()

    def action_next_note(self) -> None:
        self._commit_current()
        if self._idx < len(self._notes):
            self._idx += 1
        self._load_current_into_input()

    def on_key(self, event) -> None:
        # Keep Up/Down for note navigation while input is focused.
        if event.key == "up":
            self.action_prev_note()
            event.stop()
        elif event.key == "down":
            self.action_next_note()
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_prev":
            self.action_prev_note()
        elif event.button.id == "btn_next":
            self.action_next_note()
        elif event.button.id == "btn_delete":
            if not self._is_draft():
                del self._notes[self._idx]
                if self._idx > len(self._notes):
                    self._idx = len(self._notes)
                self._load_current_into_input()
        elif event.button.id == "btn_clear":
            self._notes.clear()
            self._idx = 0
            self._load_current_into_input()
        elif event.button.id == "btn_save":
            self._commit_current()
            self.dismiss(self._serialize_notes())

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.action_next_note()


class ThresholdScreen(ModalScreen):
    """Enter a measured value to check against upper/lower thresholds."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str, upper: str, lower: str) -> None:
        super().__init__()
        self._label = label
        self._upper = upper
        self._lower = lower

    def compose(self) -> ComposeResult:
        parts: list[str] = []
        if self._upper:
            parts.append(f"Upper <= {self._upper}")
        if self._lower:
            parts.append(f"Lower >= {self._lower}")
        bounds = "  |  ".join(parts) if parts else "No bounds configured"

        with Vertical(id="modal_box"):
            yield Static("Threshold Check", id="modal_title")
            yield Static(self._label, id="thresh_step_label")
            yield Static(bounds,      id="thresh_bounds")
            yield Input(placeholder="Enter measured value...", id="thresh_inp")
            with Horizontal(id="modal_btns"):
                yield Button("Submit", variant="primary", id="btn_submit")
                yield Button("Cancel",                   id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_submit":
            self._submit()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        self.dismiss(self.query_one("#thresh_inp", Input).value.strip())


class ManualResultScreen(ModalScreen):
    """Prompt operator to manually choose PASS or FAIL for a step."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str) -> None:
        super().__init__()
        self._label = label

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_box"):
            yield Static("Manual Pass/Fail", id="modal_title")
            yield Static(self._label, id="thresh_step_label")
            yield Static("Did this step pass or fail?", id="thresh_bounds")
            with Horizontal(id="modal_btns"):
                yield Button("Pass", variant="success", id="btn_pass")
                yield Button("Fail", variant="error", id="btn_fail")
                yield Button("Cancel", variant="default", id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_pass":
            self.dismiss("PASS")
        elif event.button.id == "btn_fail":
            self.dismiss("FAIL")
        else:
            self.dismiss(None)


class RequiredTextScreen(ModalScreen):
    """Prompt operator for required text entry (e.g., serial number)."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str) -> None:
        super().__init__()
        self._label = label

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_box"):
            yield Static("Required Text Entry", id="modal_title")
            yield Static(self._label, id="thresh_step_label")
            yield Static("Enter required text (e.g., serial number)", id="thresh_bounds")
            yield Input(placeholder="Type required text...", id="required_text_inp")
            with Horizontal(id="modal_btns"):
                yield Button("Submit", variant="primary", id="btn_submit")
                yield Button("Cancel", variant="default", id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_submit":
            self.dismiss(self.query_one("#required_text_inp", Input).value.strip())
        else:
            self.dismiss(None)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.dismiss(self.query_one("#required_text_inp", Input).value.strip())


class StepScreen(ModalScreen):
    """Add or edit a task with optional validation controls."""
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "prev_item", "Previous Item", show=False),
        Binding("down", "next_item", "Next Item", show=False),
    ]

    def __init__(
        self,
        existing: Step | None = None,
        title: str = "Add Task",
        allow_thresholds: bool = True,
        allow_main_quest: bool = False,
        multi_mode: bool = False,
        parent_label: str = "",
    ) -> None:
        super().__init__()
        self._ex    = existing
        self._title = title
        self._allow_thresholds = allow_thresholds
        self._allow_main_quest = allow_main_quest
        self._multi_mode = multi_mode
        self._parent_label = parent_label
        self._items: list[dict[str, str | bool]] = []
        self._idx = 0

    @staticmethod
    def _parse_float(raw: str) -> float | None:
        text = raw.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_percent(raw: str) -> float | None:
        text = raw.strip().replace("%", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _format_number(value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    def _apply_tolerance_thresholds(self) -> None:
        if not self._allow_thresholds:
            return
        nominal_raw = self.query_one("#step_nominal", Input).value
        tolerance_raw = self.query_one("#step_tolerance", Input).value
        nominal = self._parse_float(nominal_raw)
        tolerance_pct = self._parse_percent(tolerance_raw)
        if nominal is None or tolerance_pct is None:
            return

        delta = nominal * (abs(tolerance_pct) / 100.0)
        upper = nominal + delta
        lower = nominal - delta
        self.query_one("#step_ut", Input).value = self._format_number(upper)
        self.query_one("#step_lt", Input).value = self._format_number(lower)

    def _input_payload(self) -> dict[str, str | bool]:
        upper = self.query_one("#step_ut", Input).value.strip() if self._allow_thresholds else ""
        lower = self.query_one("#step_lt", Input).value.strip() if self._allow_thresholds else ""
        nominal = self.query_one("#step_nominal", Input).value.strip() if self._allow_thresholds else ""
        tolerance = self.query_one("#step_tolerance", Input).value.strip() if self._allow_thresholds else ""
        note = self.query_one("#step_note", Input).value.strip() if self._allow_thresholds else ""
        main_quest = self.query_one("#step_main_quest", Switch).value if self._allow_main_quest else False
        manual_pf = self.query_one("#step_manual_pf", Switch).value if self._allow_thresholds else False
        requires_text_input = self.query_one("#step_requires_text", Switch).value if self._allow_thresholds else False
        return {
            "label": self.query_one("#step_label", Input).value.strip(),
            "threshold_upper": upper,
            "threshold_lower": lower,
            "target_value": nominal,
            "tolerance_pct": tolerance,
            "note": note,
            "main_quest": main_quest,
            "manual_pass_fail": manual_pf,
            "requires_text_input": requires_text_input,
        }

    def _set_inputs_from_payload(self, payload: dict[str, str | bool] | None = None) -> None:
        payload = payload or {
            "label": "",
            "threshold_upper": "",
            "threshold_lower": "",
            "target_value": "",
            "tolerance_pct": "",
            "note": "",
            "main_quest": False,
            "manual_pass_fail": False,
            "requires_text_input": False,
        }
        self.query_one("#step_label", Input).value = payload.get("label", "")
        if self._allow_thresholds:
            self.query_one("#step_nominal", Input).value = payload.get("target_value", "")
            self.query_one("#step_tolerance", Input).value = payload.get("tolerance_pct", "")
            self.query_one("#step_ut", Input).value = payload.get("threshold_upper", "")
            self.query_one("#step_lt", Input).value = payload.get("threshold_lower", "")
            self.query_one("#step_note", Input).value = payload.get("note", "")
            self.query_one("#step_manual_pf", Switch).value = bool(payload.get("manual_pass_fail", False))
            self.query_one("#step_requires_text", Switch).value = bool(payload.get("requires_text_input", False))
        if self._allow_main_quest:
            self.query_one("#step_main_quest", Switch).value = bool(payload.get("main_quest", False))

    def _is_draft(self) -> bool:
        return self._idx >= len(self._items)

    def _commit_current(self) -> None:
        payload = self._input_payload()
        if not payload["label"]:
            return

        if self._is_draft():
            self._items.append(payload)
            self._idx = len(self._items)
            return

        self._items[self._idx] = payload

    def _refresh_multi_meta(self) -> None:
        if not self._multi_mode:
            return

        meta = self.query_one("#step_meta", Static)
        preview = self.query_one("#step_existing", Static)
        delete_btn = self.query_one("#btn_delete", Button)

        if self._is_draft():
            meta.update(f"Draft Item {len(self._items) + 1} of {len(self._items) + 1}")
            delete_btn.disabled = True
        else:
            meta.update(f"Editing Item {self._idx + 1} of {len(self._items)}")
            delete_btn.disabled = False

        lines: list[str] = []
        for i, item in enumerate(self._items, start=1):
            parts = [f"{i}. {item['label']}"]
            if item["threshold_upper"] or item["threshold_lower"]:
                parts.append("[T]")
            if bool(item.get("manual_pass_fail", False)):
                parts.append("[B]")
            if bool(item.get("requires_text_input", False)):
                parts.append("[I]")
            if bool(item.get("main_quest", False)):
                parts.append("[M]")
            lines.append("  ".join(parts))
        preview.update("\n".join(lines) if lines else "No saved items yet.")

    def _load_current_into_inputs(self) -> None:
        if not self._multi_mode:
            return
        if self._is_draft():
            self._set_inputs_from_payload(None)
        else:
            self._set_inputs_from_payload(self._items[self._idx])
        self._refresh_multi_meta()

    def compose(self) -> ComposeResult:
        ex = self._ex
        with Vertical(id="modal_box"):
            with VerticalScroll(id="step_modal_scroll"):
                yield Static(self._title, id="modal_title")
                if self._parent_label:
                    yield Label("Adding under")
                    yield Static(self._parent_label, id="step_parent")
                if self._multi_mode:
                    yield Label("Added Items")
                    yield Static("", id="step_existing")
                    yield Static("", id="step_meta")
                yield Label("Label")
                yield Input(
                    value=ex.label if ex else "",
                    placeholder="Task name...", id="step_label",
                )
                if self._allow_main_quest:
                    yield Label("Main Quest")
                    with Horizontal(id="step_main_quest_row"):
                        yield Switch(value=ex.main_quest if ex else False, id="step_main_quest")
                        yield Static("Main Quest", id="step_main_quest_label")
                if self._allow_thresholds:
                    yield Static(
                        "Value is a user defined number that the upper and lower limits are based on. "
                        "Tolerance represents the percentage above and below the target value.",
                        id="step_thresh_help",
                    )
                    yield Label("Target Value +/- Tolerance")
                    with Horizontal(id="step_tol_row"):
                        yield Input(
                            placeholder="Value, e.g. 3.3", id="step_nominal",
                        )
                        yield Static("", id="step_tol_divider")
                        yield Input(
                            placeholder="Tolerance, e.g. 5%", id="step_tolerance",
                        )
                    yield Static(
                        "User defined Max and Min values.",
                        id="step_thresh_hint",
                    )
                    yield Label("Upper Limit  (optional)")
                    yield Input(
                        value=ex.threshold_upper if ex else "",
                        placeholder="Max pass value, e.g. 5.3", id="step_ut",
                    )
                    yield Label("Lower Limit  (optional)")
                    yield Input(
                        value=ex.threshold_lower if ex else "",
                        placeholder="Min pass value, e.g. 4.7", id="step_lt",
                    )
                    yield Label("Notes  (optional)")
                    yield Input(
                        value=ex.note if ex else "",
                        placeholder="Add build-time note...", id="step_note",
                    )
                    yield Label("Boolean  (manual pass/fail)")
                    yield Static(
                        "When enabled, the operator decides PASS or FAIL.",
                        id="step_boolean_desc",
                    )
                    with Horizontal(id="step_boolean_row"):
                        yield Switch(value=ex.manual_pass_fail if ex else False, id="step_manual_pf")
                        yield Static("Pass/Fail", id="step_boolean_label")
                    yield Label("Input Required")
                    yield Static(
                        "When enabled, operator must enter text (e.g., serial number) during run.",
                        id="step_input_desc",
                    )
                    with Horizontal(id="step_input_row"):
                        yield Switch(value=ex.requires_text_input if ex else False, id="step_requires_text")
                        yield Static("Text Input", id="step_input_label")
                if self._multi_mode:
                    with Horizontal(id="note_nav_btns"):
                        yield Button("Up",      variant="default", id="btn_prev")
                        yield Button("Down",    variant="success", id="btn_next")
                        yield Button("Delete",  variant="error",   id="btn_delete")
                with Horizontal(id="modal_btns"):
                    yield Button("Save",   variant="primary", id="btn_save")
                    yield Button("Cancel",                   id="btn_cancel")

    def on_mount(self) -> None:
        if self._multi_mode:
            self._load_current_into_inputs()

    def action_prev_item(self) -> None:
        if not self._multi_mode:
            return
        self._commit_current()
        if self._is_draft() and self._items:
            self._idx = len(self._items) - 1
        elif self._idx > 0:
            self._idx -= 1
        self._load_current_into_inputs()

    def action_next_item(self) -> None:
        if not self._multi_mode:
            return
        self._commit_current()
        if self._idx < len(self._items):
            self._idx += 1
        self._load_current_into_inputs()

    def on_key(self, event) -> None:
        if not self._multi_mode:
            return
        if event.key == "up":
            self.action_prev_item()
            event.stop()
        elif event.key == "down":
            self.action_next_item()
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_prev":
            self.action_prev_item()
        elif event.button.id == "btn_next":
            self.action_next_item()
        elif event.button.id == "btn_delete":
            if self._multi_mode and not self._is_draft():
                del self._items[self._idx]
                if self._idx > len(self._items):
                    self._idx = len(self._items)
                self._load_current_into_inputs()
        elif event.button.id == "btn_save":
            self._submit()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._submit()

    def on_input_changed(self, event: Input.Changed) -> None:
        if not self._allow_thresholds:
            return
        if event.input.id in ("step_nominal", "step_tolerance"):
            self._apply_tolerance_thresholds()

    def _submit(self) -> None:
        if self._multi_mode:
            self._commit_current()
            items = [item for item in self._items if item["label"]]
            if not items:
                return
            self.dismiss(items)
            return

        label = self.query_one("#step_label", Input).value.strip()
        if not label:
            return
        upper = self.query_one("#step_ut", Input).value.strip() if self._allow_thresholds else ""
        lower = self.query_one("#step_lt", Input).value.strip() if self._allow_thresholds else ""
        note = self.query_one("#step_note", Input).value.strip() if self._allow_thresholds else ""
        main_quest = self.query_one("#step_main_quest", Switch).value if self._allow_main_quest else False
        manual_pf = self.query_one("#step_manual_pf", Switch).value if self._allow_thresholds else False
        requires_text_input = self.query_one("#step_requires_text", Switch).value if self._allow_thresholds else False
        self.dismiss({
            "label":           label,
            "threshold_upper": upper,
            "threshold_lower": lower,
            "note": note,
            "main_quest": main_quest,
            "manual_pass_fail": manual_pf,
            "requires_text_input": requires_text_input,
        })


class ConfirmScreen(ModalScreen):
    """Simple yes/no confirmation."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._msg = message

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_box"):
            yield Static("Confirm", id="modal_title")
            yield Static(self._msg, id="confirm_msg")
            with Horizontal(id="modal_btns"):
                yield Button("Yes",    variant="error",   id="btn_yes")
                yield Button("Cancel", variant="default", id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn_yes")


class FilePickerScreen(ModalScreen):
    """Popup file/directory picker – replaces left-sidebar trees."""
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(
        self,
        mode: str,
        start: Path | None = None,
        filename: str = "",
        save_ext: str = ".prcss",
    ) -> None:
        super().__init__()
        self._mode     = mode          # "open" | "open_prcss" | "open_wrkqst" | "save" | "logs"
        self._start    = start or Path.home()
        self._filename = filename
        self._save_ext = save_ext
        self._cur_dir: Path = self._start

    def compose(self) -> ComposeResult:
        titles = {
            "open": "Open Process",
            "open_prcss": "Link Process",
            "open_wrkqst": "Carry Over To Work Quest",
            "save": "Save Process As",
            "logs": "Browse Logs",
        }
        with Vertical(id="fp_box"):
            yield Static(titles[self._mode], id="fp_title")
            yield Static(str(self._start), id="fp_path")
            if self._mode == "open":
                yield ProcessFileTree(self._start, id="fp_tree")
            elif self._mode == "open_prcss":
                yield PrcssFileTree(self._start, id="fp_tree")
            elif self._mode == "open_wrkqst":
                yield WorkQuestFileTree(self._start, id="fp_tree")
            elif self._mode == "save":
                yield DirOnlyTree(self._start, id="fp_tree")
                yield Label("Filename")
                yield Input(value=self._filename, placeholder=f"process{self._save_ext}", id="fp_name")
            elif self._mode == "logs":
                yield LogFileTree(self._start, id="fp_tree")
            with Horizontal(id="fp_btns"):
                if self._mode == "save":
                    yield Button("Save", variant="primary", id="fp_ok")
                yield Button("Cancel", variant="default", id="fp_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fp_cancel":
            self.dismiss(None)
        elif event.button.id == "fp_ok":
            self._submit_save()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        path = Path(str(event.path))
        if self._mode in ("open", "open_prcss", "open_wrkqst", "logs"):
            self.dismiss(path)
        elif self._mode == "save":
            self._cur_dir = path.parent
            self.query_one("#fp_path", Static).update(str(self._cur_dir))
            self.query_one("#fp_name", Input).value = path.stem

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self._cur_dir = Path(str(event.path))
        self.query_one("#fp_path", Static).update(str(self._cur_dir))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_save()

    def _submit_save(self) -> None:
        name = self.query_one("#fp_name", Input).value.strip()
        if not name:
            return
        if not name.endswith(self._save_ext):
            name += self._save_ext
        self.dismiss(self._cur_dir / name)


class RunIDScreen(ModalScreen):
    """Prompt for a unique run identifier before spawning a process instance."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, process_name: str) -> None:
        super().__init__()
        self._process_name = process_name

    def compose(self) -> ComposeResult:
        with Vertical(id="run_id_box"):
            yield Static("Start New Run", id="modal_title")
            yield Static(self._process_name, id="thresh_step_label")
            yield Label("Unique Run Identifier  (optional)")
            yield Input(placeholder="e.g. Unit-42, Line-B, John...", id="run_id_inp")
            with Horizontal(id="modal_btns"):
                yield Button("Start",  variant="primary",  id="btn_start")
                yield Button("Cancel", variant="default",  id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_start":
            self.dismiss(self.query_one("#run_id_inp", Input).value.strip())

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.dismiss(self.query_one("#run_id_inp", Input).value.strip())


class NewFileTypeScreen(ModalScreen):
    """Choose whether a new file is a reusable template, unique process, or work quest."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def on_mount(self) -> None:
        # Avoid auto-focusing the first button to prevent harsh focus tint.
        self.app.set_focus(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="new_file_type_box"):
            yield Static("New File Type", id="modal_title")
            yield Static("Choose what you want to create.", id="confirm_msg")
            with Horizontal(id="modal_btns"):
                yield Button("Process Template", variant="primary", id="btn_template")
                yield Button("Unique Process", variant="warning", id="btn_unique")
                yield Button("Work Quest (.wrkqst)", variant="success", id="btn_wrkqst")
                yield Button("Cancel", variant="default", id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_template":
            self.dismiss("process_template")
        elif event.button.id == "btn_unique":
            self.dismiss("process_unique")
        elif event.button.id == "btn_wrkqst":
            self.dismiss("work_quest")
        else:
            self.dismiss(None)


class SplashScreen(ModalScreen):
    """Startup splash with typed welcome text."""

    _MESSAGE = "WELCOME TO VERITRAKK"
    _FIELD_WIDTH = len(_MESSAGE)
    _CHAR_DELAY_SECONDS = 0.05
    _HOLD_SECONDS = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._typed_len = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="splash_box"):
            yield Static("", id="splash_text")

    def on_mount(self) -> None:
        self.set_timer(self._CHAR_DELAY_SECONDS, self._type_next_char)

    def _type_next_char(self) -> None:
        if self._typed_len < len(self._MESSAGE):
            self._typed_len += 1
            current = self._MESSAGE[: self._typed_len]
            # Fixed-width right-justified rendering gives a consistent one-column shift per char.
            self.query_one("#splash_text", Static).update(current.rjust(self._FIELD_WIDTH))
            self.set_timer(self._CHAR_DELAY_SECONDS, self._type_next_char)
            return
        self.set_timer(self._HOLD_SECONDS, self._close_splash)

    def _close_splash(self) -> None:
        # Use a plain method callback so the timer doesn't try to await dismiss().
        self.dismiss(None)


# ── Main Application ──────────────────────────────────────────────────────────

class VeriTrakkApp(App):
    CSS_PATH  = "veritrakk.tcss"
    TITLE     = "VeriTrakk"
    SUB_TITLE = "Westbound Designs"

    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        # Run-mode task actions
        Binding("right", "complete_step",   "Complete",  show=False, priority=True),
        Binding("left",  "uncomplete_step", "Un-do",     show=False, priority=True),
        Binding("n",     "note_step",       "Note",      show=True, priority=True),
        Binding("p",     "pause_step",      "Pause",     show=True),
        Binding("c",     "toggle_clock",    "Clock In/Out", show=True),
        # Build-mode actions
        Binding("a",      "add_step",      "Add Task",    show=False),
        Binding("s",      "add_sub_step",  "Add Sub Task", show=False),
        Binding("e",      "edit_step",     "Edit",        show=False),
        Binding("d",      "delete_step",   "Delete",      show=False),
        Binding("ctrl+up",   "shift_step_up",   "Shift Up",   show=False),
        Binding("ctrl+down", "shift_step_down", "Shift Down", show=False),
        Binding("l",      "link_process",    "Link Process", show=False),
        Binding("ctrl+s", "save_build",    "Save",        show=False),
        Binding("r",      "run_linked_process", "Run Process", show=True),
        Binding("b",      "back_to_work_quest", "Back To Work Quest", show=True),
        Binding("x",      "close_active", "Close Active", show=True),
        # Global
        Binding("escape", "go_back", "Back", show=True),
        Binding("q",      "quit",    "Quit", show=True),
    ]

    # ── Internal state ────────────────────────────────────────────────────────
    _mode:              str           = "home"
    _process:           Process | None = None
    _proc_path:         Path    | None = None
    _build_proc:        Process | None = None
    _build_dir:         Path    | None = None
    _build_path:        Path    | None = None  # set when editing an existing file
    _build_root_path:   Path    | None = None  # base template for spawned instances
    _build_kind:        str           = "process"
    _build_spawn_instances: bool      = True
    _pending_thresh_idx: int           = -1
    _pending_manual_idx: int           = -1
    _pending_text_idx: int             = -1
    _syncing_clock_switch: bool        = False
    _return_wq_path:    Path | None    = None
    _return_wq_step_idx: int | None    = None
    _matrix_top_columns: list[dict[str, int]] = []
    _matrix_bottom_columns: list[dict[str, int]] = []
    _matrix_top_words: list[dict[str, int | str]] = []
    _matrix_bottom_words: list[dict[str, int | str]] = []

    # ── Layout ────────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="toolbar"):
            yield Button("New",    id="btn_new",    classes="toolbar_btn")
            yield Button("Open",   id="btn_open",   classes="toolbar_btn")
            yield Button("Resume", id="btn_resume", classes="toolbar_btn")
            yield Button("Build",  id="btn_build",  classes="toolbar_btn")
            yield Button("Logs",   id="btn_logs",   classes="toolbar_btn")
            yield Static("", id="status_bar")

        with Horizontal(id="main"):
            # ── Sidebar (mode-driven) ──────────────────────────────────────
            with ContentSwitcher(id="sidebar", initial="side_home"):
                # home
                with Vertical(id="side_home"):
                    yield Static("", id="matrix_top")
                    yield Static(
                        " VeriTrakk\n Process Tracking\n Westbound Designs",
                        id="logo",
                    )
                    yield Static("", id="matrix_bottom")

                # run
                with Vertical(id="side_run"):
                    yield Static("", id="run_name")
                    yield Static("", id="run_progress")
                    yield Static("", id="run_step_info")

                # build
                with Vertical(id="side_build"):
                    yield Static("Building process:", id="side_build_title")
                    yield Static("", id="build_file_label")

            # ── Content area ───────────────────────────────────────────────
            with ContentSwitcher(id="content", initial="view_home"):
                # home
                with VerticalScroll(id="view_home"):
                    yield Markdown(WELCOME_MD, id="home_md")

                # run: process tree
                with Vertical(id="view_run"):
                    with Horizontal(id="run_clock_strip"):
                        yield Digits("00:00:00", id="quest_digit")
                        with Horizontal(id="run_clock_toggle_row"):
                            yield Switch(value=False, id="quest_clock_switch")
                            yield Static("CLOCKED OUT", id="quest_clock_state")
                    yield Tree("", id="process_tree")

                # build: toolbar + builder tree
                with Vertical(id="view_build"):
                    with Horizontal(id="build_toolbar"):
                        yield Input(placeholder="Process name...", id="build_name_inp")
                        yield Button("+ Task",    id="btn_add_step",    variant="success", classes="build_btn")
                        yield Button("+ Sub Task", id="btn_add_sub",     variant="success", classes="build_btn")
                        yield Button("Delete",     id="btn_del_step",    variant="error",   classes="build_btn")
                        yield Button("Save",       id="btn_save_proc",   variant="primary", classes="build_btn")
                        yield Button("Edit",       id="btn_edit_step",   variant="default", classes="build_btn")
                        yield Button("↑ Shift Up",   id="btn_shift_up",   variant="default", classes="build_btn")
                        yield Button("↓ Shift Down", id="btn_shift_down", variant="default", classes="build_btn")
                        yield Button("Link Process", id="btn_link_process", variant="default", classes="build_btn")
                        yield Button("Carry Over", id="btn_carry_over", variant="warning", classes="build_btn")
                    yield Tree("New Process", id="builder_tree")

                # logs viewer
                with Vertical(id="view_logs"):
                    yield Log(id="log_output", auto_scroll=False)

        with Horizontal(id="close_bar"):
            yield Static("", id="close_action_text")

        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def on_mount(self) -> None:
        proc_tree = self.query_one("#process_tree", Tree)
        proc_tree.auto_expand = False
        proc_tree.root.expand()
        build_tree = self.query_one("#builder_tree", Tree)
        build_tree.auto_expand = False
        build_tree.root.expand()
        matrix_top = self.query_one("#matrix_top", Static)
        matrix_bottom = self.query_one("#matrix_bottom", Static)
        matrix_top.styles.color = MATRIX_RAIN_COLOR
        matrix_bottom.styles.color = MATRIX_RAIN_COLOR
        self.set_interval(1, self._tick_clock)
        self.set_interval(MATRIX_RAIN_TICK_SECONDS, self._tick_matrix_rain)
        self._tick_matrix_rain()
        self.push_screen(SplashScreen(), callback=lambda _: self._show_home())

    def _tick_matrix_rain(self) -> None:
        if self._mode != "home":
            return
        top = self.query_one("#matrix_top", Static)
        bottom = self.query_one("#matrix_bottom", Static)

        panel_top_width = max(8, top.size.width - 2)
        panel_bottom_width = max(8, bottom.size.width - 2)
        panel_shared_width = min(panel_top_width, panel_bottom_width)

        if MATRIX_RAIN_WIDTH <= 0:
            matrix_width = panel_shared_width
        else:
            matrix_width = max(1, min(panel_shared_width, MATRIX_RAIN_WIDTH))

        top_rows = max(MATRIX_RAIN_TOP_ROWS, max(1, top.size.height - 2))
        bottom_rows = max(MATRIX_RAIN_BOTTOM_ROWS, max(1, bottom.size.height - 2))

        total_rows = top_rows + bottom_rows
        grid, sneaky_cells = self._render_matrix_region(
            self._matrix_top_columns,
            self._matrix_top_words,
            total_rows,
            matrix_width,
        )
        top.update(self._render_matrix_slice(grid, sneaky_cells, 0, top_rows))
        bottom.update(self._render_matrix_slice(grid, sneaky_cells, top_rows, total_rows))

    def _render_matrix_region(
        self,
        columns: list[dict[str, int]],
        words: list[dict[str, int | str]],
        rows: int,
        width: int,
    ) -> tuple[list[list[str]], set[tuple[int, int]]]:
        width = max(1, width)
        chars = (MATRIX_RAIN_RANDOM_CHARS[:3] or "01#")[:3]

        density = max(0.0, min(1.0, MATRIX_RAIN_DENSITY))
        min_interval = max(1, MATRIX_RAIN_COLUMN_MIN_INTERVAL_TICKS)
        max_interval = max(min_interval, MATRIX_RAIN_COLUMN_MAX_INTERVAL_TICKS)
        change_cycles = max(1, MATRIX_RAIN_COLUMN_CHAR_CHANGE_CYCLES)

        # Higher density means faster per-column growth (shorter update intervals).
        effective_max_interval = max(
            min_interval,
            int(round(max_interval - (max_interval - min_interval) * density)),
        )

        while len(columns) < width:
            interval = random.randint(min_interval, effective_max_interval)
            columns.append(
                {
                    "height": 0,
                    "interval": interval,
                    "next_tick": random.randint(0, interval),
                    "char_idx": random.randrange(len(chars)),
                    "cycles": 0,
                }
            )
        if len(columns) > width:
            del columns[width:]

        advanced_columns: set[int] = set()
        for col_idx, col in enumerate(columns):
            next_tick = int(col.get("next_tick", 0))
            if next_tick > 0:
                col["next_tick"] = next_tick - 1
                continue

            advanced_columns.add(col_idx)
            height = int(col.get("height", 0))
            if height < rows:
                col["height"] = height + 1
            else:
                col["height"] = 0
                cycles = int(col.get("cycles", 0)) + 1
                if cycles >= change_cycles:
                    cycles = 0
                    current_idx = int(col.get("char_idx", 0)) % len(chars)
                    col["char_idx"] = (current_idx + 1) % len(chars)
                col["cycles"] = cycles

            interval = random.randint(min_interval, effective_max_interval)
            col["interval"] = interval
            col["next_tick"] = interval

        if MATRIX_RAIN_SNEAKY_WORDS and random.random() < MATRIX_RAIN_SNEAKY_WORD_CHANCE:
            word = random.choice([w for w in MATRIX_RAIN_SNEAKY_WORDS if w.strip()]).upper()
            if word:
                words.append(
                    {
                        "col": random.randrange(width),
                        "top": -len(word),
                        "word": word,
                    }
                )

        next_words: list[dict[str, int | str]] = []
        for word_drop in words:
            col = int(word_drop.get("col", -1))
            top_row = int(word_drop.get("top", -1))
            if col in advanced_columns:
                top_row += 1
            word = str(word_drop.get("word", ""))
            if top_row < rows:
                word_drop["top"] = top_row
                next_words.append(word_drop)
        words[:] = next_words

        grid = [[" " for _ in range(width)] for _ in range(max(1, rows))]

        for col_idx, col in enumerate(columns):
            height = int(col.get("height", 0))
            char_idx = int(col.get("char_idx", 0)) % len(chars)
            char = chars[char_idx]
            for row in range(max(0, min(rows, height))):
                grid[row][col_idx] = char

        sneaky_cells: set[tuple[int, int]] = set()
        for word_drop in words:
            col = int(word_drop.get("col", 0))
            top_row = int(word_drop.get("top", 0))
            word = str(word_drop.get("word", ""))
            if not word or col < 0 or col >= width:
                continue
            for idx, ch in enumerate(word):
                row = top_row + idx
                if 0 <= row < rows:
                    grid[row][col] = ch
                    sneaky_cells.add((row, col))
        return grid, sneaky_cells

    def _render_matrix_slice(
        self,
        grid: list[list[str]],
        sneaky_cells: set[tuple[int, int]],
        start_row: int,
        end_row: int,
    ) -> Text:
        rendered = Text()
        sneaky_style = f"bold {MATRIX_RAIN_SNEAKY_WORD_COLOR}"

        start = max(0, start_row)
        end = min(len(grid), max(start, end_row))
        row_indices = list(range(start, end))
        if not row_indices:
            return rendered

        for idx, row_idx in enumerate(row_indices):
            line = grid[row_idx]
            for col_idx, ch in enumerate(line):
                if (row_idx, col_idx) in sneaky_cells:
                    rendered.append(ch, style=sneaky_style)
                else:
                    rendered.append(ch)
            if idx < len(row_indices) - 1:
                rendered.append("\n")
        return rendered

    # ── Mode management ───────────────────────────────────────────────────────
    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        mode_map = {
            "build": "btn_build",
            "logs":  "btn_logs",
        }
        for btn_id in ("btn_new", "btn_open", "btn_resume", "btn_build", "btn_logs"):
            self.query_one(f"#{btn_id}", Button).remove_class("active_mode")
        if mode in mode_map:
            self.query_one(f"#{mode_map[mode]}", Button).add_class("active_mode")
        self.refresh_bindings()

    def _switch(self, sidebar: str, content: str) -> None:
        self.query_one("#sidebar", ContentSwitcher).current = sidebar
        self.query_one("#content",  ContentSwitcher).current = content

    # ── Show methods ──────────────────────────────────────────────────────────
    def _show_home(self) -> None:
        self._set_mode("home")
        self._switch("side_home", "view_home")
        self.query_one("#status_bar", Static).update("")
        self._refresh_quest_clock_widgets()
        self._refresh_close_action_bar()

    def _open_picker(self) -> None:
        start = Path.home()
        self.push_screen(
            FilePickerScreen("open", start=start),
            callback=lambda path: self._load_process(path) if path else None,
        )

    def _build_picker(self) -> None:
        start = Path.home()
        self.push_screen(
            FilePickerScreen("open", start=start),
            callback=self._on_build_selected,
        )

    def _logs_picker(self) -> None:
        self.push_screen(
            FilePickerScreen("logs", start=Path.home()),
            callback=self._on_logs_selected,
        )

    def _on_logs_selected(self, path: Path | None) -> None:
        if path is None:
            return
        if path.suffix in (".prcsslog", ".wrkqstlog"):
            self._set_mode("logs")
            self._view_log(path)
        elif path.suffix in (".prcss", ".wrkqst") and "#COMPLETE" in path.name:
            self.push_screen(
                ConfirmScreen(
                    f"Publish and dissolve:\n{path.name}\n\n"
                    "This will write a log file and delete the source file."
                ),
                callback=lambda confirmed: self._do_dissolve(path) if confirmed else None,
            )

    def _show_run(self) -> None:
        self._set_mode("run")
        self._switch("side_run", "view_run")
        self._rebuild_proc_tree()
        self._refresh_run_sidebar()
        self._refresh_quest_clock_widgets()
        self._refresh_status()
        self._refresh_close_action_bar()
        self.query_one("#process_tree", Tree).focus()

    def _show_build(self, existing_path: Path | None = None) -> None:
        self._set_mode("build")
        if existing_path is not None:
            try:
                self._build_proc = load_process(existing_path)
            except Exception:
                return
            self._build_path = existing_path
            self._build_dir  = existing_path.parent
            self._build_kind = self._build_proc.kind
            self._build_spawn_instances = self._build_proc.spawn_instances
            self._build_root_path = self._root_template_path(existing_path)
        else:
            self._build_path = None
            self._build_dir = None
            self._build_root_path = None
            default_name = "New Work Quest" if self._build_kind == "work_quest" else "New Process"
            self._build_proc = Process(
                name=default_name,
                kind=self._build_kind,
                spawn_instances=self._build_spawn_instances,
            )

        name_inp = self.query_one("#build_name_inp", Input)
        name_inp.placeholder = (
            "Work Quest name..." if self._build_proc.kind == "work_quest" else "Process name..."
        )
        name_inp.value = self._build_proc.name
        self._refresh_build_terminology()
        self._rebuild_builder_tree()
        self._update_build_file_label()
        self._switch("side_build", "view_build")
        self._refresh_quest_clock_widgets()
        self._refresh_status()
        self._refresh_close_action_bar()
        self.query_one("#build_name_inp", Input).focus()

    def _build_terms(self) -> tuple[str, str]:
        if self._build_proc and self._build_proc.kind == "process":
            return ("Step", "Sub Step")
        return ("Task", "Sub Task")

    def _step_number(self, proc: Process, step_idx: int) -> str:
        """Return hierarchical step numbering (e.g., 1, 2.1, 2.1.1)."""
        if step_idx < 0 or step_idx >= len(proc.steps):
            return ""

        parts: list[str] = []
        current_idx = step_idx

        while True:
            parent_idx = proc.parent_of(current_idx)
            if parent_idx is None:
                top_count = sum(1 for s in proc.steps[: current_idx + 1] if s.level == 1)
                parts.append(str(top_count))
                break

            siblings = proc.children_of(parent_idx)
            ordinal = 1
            for pos, (sib_idx, _) in enumerate(siblings, start=1):
                if sib_idx == current_idx:
                    ordinal = pos
                    break
            parts.append(str(ordinal))
            current_idx = parent_idx

        return ".".join(reversed(parts))

    def _refresh_build_terminology(self) -> None:
        item_term, sub_item_term = self._build_terms()
        self.query_one("#btn_add_step", Button).label = f"+ {item_term}"
        self.query_one("#btn_add_sub", Button).label = f"+ {sub_item_term}"
        is_process = self._build_proc is not None and self._build_proc.kind == "process"
        is_work_quest = self._build_proc is not None and self._build_proc.kind == "work_quest"
        self.query_one("#btn_shift_up", Button).display = is_process
        self.query_one("#btn_shift_down", Button).display = is_process
        self.query_one("#btn_link_process", Button).display = is_work_quest
        self.query_one("#btn_carry_over", Button).display = is_work_quest
        if self._build_proc and self._build_proc.kind == "process":
            kind_label = "Template" if self._build_proc.spawn_instances else "Unique"
            self.query_one("#side_build_title", Static).update(f"Building process ({kind_label}):")
        elif self._build_proc and self._build_proc.kind == "work_quest":
            self.query_one("#side_build_title", Static).update("Building work quest:")
        else:
            self.query_one("#side_build_title", Static).update("Building process:")

    # ── Button handling ───────────────────────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id

        # Toolbar
        if bid == "btn_new":
            self._start_new_process(); return
        if bid == "btn_open":
            self._open_picker(); return
        if bid == "btn_resume":
            self._resume(); return
        if bid == "btn_build":
            self._pick_build_target(); return
        if bid == "btn_logs":
            self._logs_picker(); return

        # Builder toolbar
        if bid == "btn_add_step":
            self.action_add_step(); return
        if bid == "btn_add_sub":
            self.action_add_sub_step(); return
        if bid == "btn_link_process":
            self.action_link_process(); return
        if bid == "btn_carry_over":
            self.action_carry_over(); return
        if bid == "btn_edit_step":
            self.action_edit_step(); return
        if bid == "btn_del_step":
            self.action_delete_step(); return
        if bid == "btn_shift_up":
            self.action_shift_step_up(); return
        if bid == "btn_shift_down":
            self.action_shift_step_down(); return
        if bid == "btn_save_proc":
            self.action_save_build(); return

    # ── New / Open / Resume / Build flows ─────────────────────────────────────
    def _start_new_process(self) -> None:
        self.push_screen(NewFileTypeScreen(), callback=self._on_new_file_type)

    def _on_new_file_type(self, kind: str | None) -> None:
        if kind is None:
            return
        self._build_kind = "work_quest" if kind == "work_quest" else "process"
        self._build_spawn_instances = kind != "process_unique"
        self._build_path = None
        default_name = "New Work Quest" if self._build_kind == "work_quest" else "New Process"
        self._build_proc = Process(
            name=default_name,
            kind=self._build_kind,
            spawn_instances=self._build_spawn_instances,
        )
        self._show_build()

    def _pick_build_target(self) -> None:
        if self._process and self._proc_path:
            self._show_build(existing_path=self._proc_path)
        else:
            self._build_picker()

    def _on_build_selected(self, path: Path | None) -> None:
        if path is None:
            return
        self._show_build(existing_path=path)

    def _root_template_path(self, path: Path) -> Path | None:
        """Return the base template path for a spawned .prcss instance, if available."""
        if path.suffix != ".prcss" or "#" not in path.stem:
            return None

        before_hash = path.stem.split("#", 1)[0]
        candidate_names = [before_hash]
        tagged = re.match(r"^(.*)\[[^\]]+\]$", before_hash)
        if tagged and tagged.group(1):
            candidate_names.append(tagged.group(1))

        seen: set[str] = set()
        for candidate in candidate_names:
            if candidate in seen:
                continue
            seen.add(candidate)
            base_path = path.with_name(candidate + path.suffix)
            if not base_path.exists():
                continue
            try:
                base_proc = load_process(base_path)
            except Exception:
                continue
            if base_proc.kind == "process":
                return base_path

        return None

    def _resume(self) -> None:
        sess = load_session()
        if not sess:
            return
        directory, file_name = sess
        if not file_name.strip():
            return
        path = directory / file_name
        if not path.exists() or not path.is_file():
            return
        self._load_process(path)

    def _refresh_close_action_bar(self) -> None:
        bar = self.query_one("#close_action_text", Static)
        if self._process is None:
            bar.update("No active process or work quest")
            return
        target = "Work Quest" if self._process.kind == "work_quest" else "Process"
        bar.update(f"[X] Close {target}")

    def action_close_active(self) -> None:
        if self._process is None:
            return
        self._process = None
        self._proc_path = None
        self._clear_work_quest_return_context()
        save_session(Path.home(), "")
        self._show_home()

    def _load_process(self, file_path: Path) -> None:
        self._clear_work_quest_return_context()
        try:
            proc = load_process(file_path)
        except OSError:
            return
        self._build_spawn_instances = proc.spawn_instances
        # Reusable templates prompt for a run ID; unique processes open directly.
        if proc.kind == "process" and proc.spawn_instances and file_path.suffix == ".prcss" and "#" not in file_path.stem:
            self.push_screen(
                RunIDScreen(file_path.stem),
                callback=lambda run_id: self._spawn_instance(file_path, run_id),
            )
            return
        self._open_process_file(file_path)

    def _spawn_instance(self, base_path: Path, run_id: str | None) -> None:
        if run_id is None:
            return  # user cancelled
        try:
            instance_path = create_process_instance(base_path, run_id)
        except OSError:
            self.notify("Could not create process instance.", severity="error")
            return
        self.notify(
            f"New run: {instance_path.name}",
            title="Process Instance Created",
            severity="information",
        )
        self._open_process_file(instance_path)

    def _open_process_file(self, file_path: Path) -> None:
        try:
            proc = load_process(file_path)
        except OSError:
            return
        if not proc.kind:
            proc.kind = "work_quest" if file_path.suffix == ".wrkqst" else "process"
        self._process   = proc
        self._proc_path = file_path
        self._build_dir = file_path.parent
        self._sync_parent_states_from_children()
        save_session(file_path.parent, file_path.name)
        self._show_run()

    def _clear_work_quest_return_context(self) -> None:
        self._return_wq_path = None
        self._return_wq_step_idx = None

    def _is_work_quest_active(self) -> bool:
        return (
            self._mode == "run"
            and self._process is not None
            and self._process.kind == "work_quest"
        )

    def _tick_clock(self) -> None:
        if self._mode != "run" or not self._process:
            return
        has_live_step_timer = self._has_live_step_timer()
        if self._is_work_quest_active():
            self._refresh_quest_clock_widgets()
        if has_live_step_timer:
            self._refresh_proc_tree_live()
        self._refresh_status()
        if has_live_step_timer:
            self._update_step_info()

    def _has_live_step_timer(self) -> bool:
        if not self._process or self._process.kind != "work_quest":
            return False
        for idx, step in enumerate(self._process.steps):
            if self._process.has_children(idx):
                continue
            if step.started and not step.completed and not step.paused and bool(step.active_since):
                return True
        return False

    def _compute_run_tree_metrics(
        self,
        now: datetime,
    ) -> tuple[dict[int, list[int]], dict[int, tuple[int, int]], dict[int, int]]:
        """Build immediate-children map, child completion stats, and live seconds in O(n)."""
        proc = self._process
        if not proc:
            return {}, {}, {}

        total_steps = len(proc.steps)
        children_map: dict[int, list[int]] = {i: [] for i in range(total_steps)}

        stack: list[int] = []
        for idx, step in enumerate(proc.steps):
            while stack and proc.steps[stack[-1]].level >= step.level:
                stack.pop()
            if stack:
                children_map[stack[-1]].append(idx)
            stack.append(idx)

        live_seconds: dict[int, int] = {}
        for idx, step in enumerate(proc.steps):
            total = max(0, step.duration_seconds)
            if (
                proc.kind == "work_quest"
                and step.started
                and not step.completed
                and not step.paused
                and step.active_since
            ):
                total += self._work_quest_seconds_between(proc, step.active_since, now)
            live_seconds[idx] = max(0, total)

        for idx in range(total_steps - 1, -1, -1):
            children = children_map[idx]
            if children:
                live_seconds[idx] = max(0, sum(live_seconds[child_idx] for child_idx in children))

        child_stats: dict[int, tuple[int, int]] = {}
        for idx, children in children_map.items():
            if not children:
                continue
            done = sum(1 for child_idx in children if proc.steps[child_idx].completed)
            child_stats[idx] = (done, len(children))

        return children_map, child_stats, live_seconds

    def _format_minutes(self, minutes: int) -> str:
        h = max(0, minutes // 60)
        m = max(0, minutes % 60)
        # Keep Digits fixed-width for readability.
        return f"{str(h).zfill(2)}:{str(m).zfill(2)}"

    def _format_seconds(self, total_seconds: int) -> str:
        total = max(0, total_seconds)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _work_quest_seconds_between(self, proc: Process, started_at: str, ended_at: datetime) -> int:
        """Seconds between start/end that overlap work-quest clocked-in windows."""
        try:
            start_dt = datetime.fromisoformat(started_at)
        except ValueError:
            return 0

        if ended_at <= start_dt:
            return 0

        total_seconds = 0
        active_in: datetime | None = None
        intervals: list[tuple[datetime, datetime]] = []

        for event in proc.clock_events:
            if "|" not in event:
                continue
            kind, ts = event.split("|", 1)
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                continue

            if kind == "IN":
                active_in = dt
            elif kind == "OUT" and active_in is not None:
                intervals.append((active_in, dt))
                active_in = None

        if active_in is not None:
            intervals.append((active_in, ended_at))

        for in_dt, out_dt in intervals:
            if out_dt <= in_dt:
                continue
            overlap_start = max(start_dt, in_dt)
            overlap_end = min(ended_at, out_dt)
            if overlap_end > overlap_start:
                total_seconds += int((overlap_end - overlap_start).total_seconds())

        return max(0, total_seconds)

    def _work_quest_minutes_between(self, proc: Process, started_at: str, ended_at: datetime) -> int:
        """Minutes between start/end that overlap work-quest clocked-in windows."""
        return self._work_quest_seconds_between(proc, started_at, ended_at) // 60

    def _live_step_seconds(self, step_idx: int, now: datetime | None = None) -> int:
        if not self._process:
            return 0

        step = self._process.steps[step_idx]

        # Parent nodes show rolled-up live duration from their immediate children.
        children = self._process.children_of(step_idx)
        if children:
            return max(0, sum(self._live_step_seconds(child_idx, now) for child_idx, _ in children))

        total = max(0, step.duration_seconds)
        if (
            self._process
            and self._process.kind == "work_quest"
            and step.started
            and not step.completed
            and not step.paused
            and step.active_since
        ):
            ended_at = now or datetime.now()
            total += self._work_quest_seconds_between(self._process, step.active_since, ended_at)
        return max(0, total)

    def _sync_duration_minutes(self, step: Step) -> None:
        step.duration_minutes = max(0, step.duration_seconds // 60)

    def _sync_parent_states_for_process(self, proc: Process) -> None:
        for idx in range(len(proc.steps) - 1, -1, -1):
            parent = proc.steps[idx]
            children = proc.children_of(idx)
            if not children:
                continue

            child_steps = [child for _, child in children]
            started_stamps = [child.started_at for child in child_steps if child.started_at]
            completed_stamps = [child.completed_at for child in child_steps if child.completed_at]

            any_in_progress = any(child.started and not child.completed for child in child_steps)
            any_active = any(child.started and not child.completed and not child.paused for child in child_steps)
            all_done = all(child.completed for child in child_steps)

            parent.started = any_in_progress
            parent.started_at = min(started_stamps) if (any_in_progress or all_done) and started_stamps else ""
            parent.completed = all_done
            parent.completed_at = max(completed_stamps) if all_done and completed_stamps else ""
            parent.paused = any_in_progress and not any_active
            parent.active_since = ""
            parent.duration_seconds = sum(max(0, child.duration_seconds) for child in child_steps)
            self._sync_duration_minutes(parent)

    def _sync_parent_states_from_children(self) -> None:
        if not self._process:
            return
        self._sync_parent_states_for_process(self._process)

    def _active_step_idx(self, *, exclude_idx: int | None = None) -> int | None:
        if not self._process:
            return None
        for idx, step in enumerate(self._process.steps):
            if exclude_idx is not None and idx == exclude_idx:
                continue
            # Parent steps with children are derived state and should never block starts.
            if self._process.has_children(idx):
                continue
            if step.started and not step.completed and not step.paused:
                return idx
        return None

    def _accumulate_active_minutes(self, step_idx: int, now: datetime | None = None) -> None:
        if not self._process:
            return
        step = self._process.steps[step_idx]
        if not step.active_since:
            return
        ended_at = now or datetime.now()
        step.duration_seconds += self._work_quest_seconds_between(
            self._process,
            step.active_since,
            ended_at,
        )
        self._sync_duration_minutes(step)
        step.active_since = ""

    def _refresh_quest_clock_widgets(self) -> None:
        strip = self.query_one("#run_clock_strip", Horizontal)
        digit = self.query_one("#quest_digit", Digits)
        switch = self.query_one("#quest_clock_switch", Switch)
        state = self.query_one("#quest_clock_state", Static)
        toolbar = self.query_one("#toolbar", Horizontal)
        sidebar = self.query_one("#sidebar", ContentSwitcher)
        step_info = self.query_one("#run_step_info", Static)

        themed = [strip, toolbar, sidebar, step_info]
        for widget in themed:
            widget.remove_class("clocked_in")
            widget.remove_class("clocked_out")

        if not self._is_work_quest_active():
            strip.display = False
            for widget in themed:
                widget.add_class("clocked_out")
            return

        strip.display = True
        digit.update(self._format_seconds(self._process.total_clock_seconds()))

        self._syncing_clock_switch = True
        switch.value = self._process.clocked_in
        switch.disabled = False
        self._syncing_clock_switch = False

        if self._process.clocked_in:
            for widget in themed:
                widget.add_class("clocked_in")
            switch.remove_class("clocked_out")
            switch.add_class("clocked_in")
            state.remove_class("clocked_out")
            state.add_class("clocked_in")
            state.update("CLOCKED IN")
        else:
            for widget in themed:
                widget.add_class("clocked_out")
            switch.remove_class("clocked_in")
            switch.add_class("clocked_out")
            state.remove_class("clocked_in")
            state.add_class("clocked_out")
            state.update("CLOCKED OUT")

    def _toggle_work_quest_clock(self, clock_in: bool) -> None:
        if not self._is_work_quest_active() or not self._process or not self._proc_path:
            return

        if clock_in == self._process.clocked_in:
            return

        now = datetime.now().isoformat()
        if clock_in:
            self._process.clocked_in = True
            self._process.clock_active_since = now
            self._process.clock_events.append(f"IN|{now}")
        else:
            self._process.clocked_in = False
            self._process.clock_active_since = ""
            self._process.clock_events.append(f"OUT|{now}")

        save_process(self._process, self._proc_path)
        self._refresh_quest_clock_widgets()
        self._refresh_status()

    def action_toggle_clock(self) -> None:
        if not self._is_work_quest_active() or not self._process:
            return
        self._toggle_work_quest_clock(not self._process.clocked_in)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != "quest_clock_switch" or self._syncing_clock_switch:
            return
        self._toggle_work_quest_clock(event.value)

    # ── Process tree (run mode) ───────────────────────────────────────────────
    def _rebuild_proc_tree(self) -> None:
        if not self._process:
            return
        proc = self._process
        tree = self.query_one("#process_tree", Tree)
        now = datetime.now()
        children_map, child_stats, live_seconds = self._compute_run_tree_metrics(now)

        # Remember collapsed nodes so we can restore expand/collapse state.
        collapsed: set[int] = set()
        def _collect_collapsed(node) -> None:
            if node.data is not None and node.children and not node.is_expanded:
                collapsed.add(node.data)
            for child in node.children:
                _collect_collapsed(child)

        _collect_collapsed(tree.root)

        root_label = Text(proc.name)
        if proc.completed:
            root_label.stylize("bold green")
        else:
            root_label.stylize(f"bold {_SALMON}")
        tree.reset(root_label)
        tree.root.data = None

        stack: list[tuple[int, object]] = [(0, tree.root)]
        for idx, step in enumerate(proc.steps):
            while stack and stack[-1][0] >= step.level:
                stack.pop()
            parent_node = stack[-1][1] if stack else tree.root
            number_prefix = self._step_number(proc, idx) if proc.kind == "process" else ""

            children = children_map.get(idx, [])
            sub_done, sub_total = child_stats.get(idx, (0, 0))
            live_seconds_for_step = live_seconds.get(idx, max(0, step.duration_seconds))

            if children:
                node = parent_node.add(
                    _step_label(
                        step,
                        number_prefix=number_prefix,
                        show_process_badge=proc.kind == "work_quest",
                        sub_done=sub_done,
                        sub_total=sub_total,
                        live_seconds=live_seconds_for_step,
                    ),
                    data=idx,
                    expand=idx not in collapsed,
                )
                stack.append((step.level, node))
            else:
                parent_node.add_leaf(
                    _step_label(
                        step,
                        number_prefix=number_prefix,
                        show_process_badge=proc.kind == "work_quest",
                        live_seconds=live_seconds_for_step,
                    ),
                    data=idx,
                )

        tree.root.expand()

    def _refresh_proc_tree_live(self) -> None:
        if self._mode != "run" or not self._process:
            return
        tree = self.query_one("#process_tree", Tree)
        proc = self._process
        now = datetime.now()
        children_map, child_stats, live_seconds = self._compute_run_tree_metrics(now)

        def _walk(node) -> None:
            if node.data is not None:
                idx = node.data
                step = proc.steps[idx]
                number_prefix = self._step_number(proc, idx) if proc.kind == "process" else ""
                children = children_map.get(idx, [])
                sub_done, sub_total = child_stats.get(idx, (0, 0))
                node.set_label(
                    _step_label(
                        step,
                        number_prefix=number_prefix,
                        show_process_badge=proc.kind == "work_quest",
                        sub_done=sub_done if children else None,
                        sub_total=sub_total if children else None,
                        live_seconds=live_seconds.get(idx, max(0, step.duration_seconds)),
                    )
                )
            for child in node.children:
                _walk(child)

        _walk(tree.root)

    def _refresh_run_sidebar(self) -> None:
        if not self._process:
            return
        proc = self._process
        pct  = proc.progress_pct
        item_word = "steps" if proc.kind == "process" else "tasks"
        kind_label = "Process" if proc.kind == "process" else "Work Quest"

        file_name = self._proc_path.name if self._proc_path else "(unsaved)"
        unique_id = self._extract_instance_unique_id(self._proc_path)

        name_t = Text()
        name_t.append(f'{kind_label}: ', style=f"bold {_KHAKI}")
        name_t.append(f'"{proc.name}"\n', style=f"bold {_SALMON}")
        name_t.append("File: ", style=f"bold {_KHAKI}")
        name_t.append(f"{file_name}", style=f"{_BLUE}")
        if proc.kind == "process":
            name_t.append("\nUnique ID: ", style=f"bold {_KHAKI}")
            name_t.append(f"{unique_id or 'None'}", style=f"{_BLUE}")
        self.query_one("#run_name", Static).update(name_t)

        prog_t = Text()
        prog_t.append(f"{_progress_bar(pct)}\n", style=_GREEN)
        prog_t.append(f"{proc.done_top}/{proc.total_top} {item_word}  ", style=_KHAKI)
        prog_t.append(f"{pct:.0f}%", style=_GOLD)
        if proc.kind == "work_quest":
            pending_main_quests = sum(
                1
                for step in proc.steps
                if step.level == 1 and step.main_quest and not step.completed
            )
            prog_t.append("\nPending Main Quests: ", style=f"bold {_KHAKI}")
            prog_t.append(str(pending_main_quests), style=f"bold {_GOLD}")
        self.query_one("#run_progress", Static).update(prog_t)

    def _extract_instance_unique_id(self, proc_path: Path | None) -> str:
        if proc_path is None:
            return ""
        stem = proc_path.stem.replace("#COMPLETE", "")
        match = re.match(r"^.+?\[(?P<uid>[^\]]+)\]#.+$", stem)
        return match.group("uid").strip() if match else ""

    def _refresh_status(self) -> None:
        bar = self.query_one("#status_bar", Static)
        if self._mode == "run" and self._process:
            proc = self._process
            pct  = proc.progress_pct
            t = Text("  ")
            t.append(proc.name, style=f"bold {_SALMON}")
            t.append(f"  {proc.done_top}/{proc.total_top}", style=_KHAKI)
            t.append(f"  {_progress_bar(pct, 12)}", style=_GREEN)
            t.append(f"  {pct:.0f}%", style=_GOLD)
            if proc.kind == "work_quest":
                t.append("  Time ", style="dim")
                t.append(self._format_minutes(proc.total_clock_minutes()), style=_TEAL)
                t.append("  ", style="dim")
                t.append("IN" if proc.clocked_in else "OUT", style=_GREEN if proc.clocked_in else _KHAKI)
            bar.update(t)
        elif self._mode == "build" and self._build_proc:
            t = Text("  ")
            t.append("BUILDER", style=f"bold {_SALMON}")
            t.append(f"  {self._build_proc.name}", style=_KHAKI)
            bar.update(t)
        else:
            bar.update("")
        self._refresh_close_action_bar()

    def _format_notes_for_sidebar(self, raw_notes: str) -> str:
        formatted_blocks: list[str] = []
        for raw in raw_notes.splitlines():
            line = raw.strip()
            if not line:
                continue
            match = re.match(r"^\[(.*?)\]\s*(.*)$", line)
            if match:
                ts = match.group(1).strip()
                text = match.group(2).strip()
                if text:
                    formatted_blocks.append(f"[{ts}]\n{text}")
                else:
                    formatted_blocks.append(f"[{ts}]")
                continue
            formatted_blocks.append(line)

        if formatted_blocks:
            return "\n\n".join(formatted_blocks)
        return raw_notes.strip()

    def _update_step_info(self) -> None:
        tree = self.query_one("#process_tree", Tree)
        info = self.query_one("#run_step_info", Static)
        node = tree.cursor_node
        if node is None or node.data is None or not self._process:
            self._refresh_focus_cursor_state()
            info.update("")
            return
        step_idx = node.data
        step = self._process.steps[step_idx]
        number_prefix = self._step_number(self._process, step_idx) if self._process.kind == "process" else ""
        display_label = f"{number_prefix} {step.label}" if number_prefix else step.label
        live_seconds = self._live_step_seconds(step_idx)
        t = Text()
        # Task label
        t.append(display_label + "\n", style=f"bold {_SALMON}")
        if self._process.kind == "work_quest" and step.main_quest:
            t.append("MAIN QUEST\n", style=f"bold {_GOLD}")
            t.append("Priority task for this work quest\n", style="dim")
        # Status
        if step.completed:
            if step.result == "PASS":
                t.append("\u2713 PASS\n", style=f"bold {_GREEN}")
            elif step.result == "FAIL":
                t.append("\u2717 FAIL\n", style="bold red")
            else:
                ts = ""
                if step.completed_at:
                    try:
                        dt = datetime.fromisoformat(step.completed_at)
                        ts = f"  {dt.strftime('%I:%M %p').lstrip('0')}"
                    except ValueError:
                        pass
                t.append(f"\u2713 Done{ts}\n", style=_GREEN)
            if live_seconds > 0:
                t.append(
                    f"Duration {self._format_seconds(live_seconds)}\n",
                    style=_TEAL,
                )
        elif step.started:
            if step.paused:
                t.append("\u25d4 Paused\n", style=f"bold {_PURPLE}")
            else:
                t.append("\u25d4 In Progress\n", style=f"bold {_BLUE}")
            t.append(
                f"Duration {self._format_seconds(live_seconds)}\n",
                style=_TEAL,
            )
        else:
            t.append("\u25cb Pending\n", style="dim")
            if live_seconds > 0:
                t.append(
                    f"Duration {self._format_seconds(live_seconds)}\n",
                    style=_TEAL,
                )
        # Note
        if step.note:
            t.append("\nNotes\n", style="dim")
            t.append(self._format_notes_for_sidebar(step.note), style=_KHAKI)
        # Work quest parent nodes can summarize notes from child tasks.
        if self._process.kind == "work_quest" and self._process.has_children(step_idx):
            child_notes: list[tuple[str, str]] = []
            for child_idx, child in self._process.descendants_of(step_idx):
                if not child.note.strip():
                    continue
                child_label = child.label
                if self._process.has_children(child_idx):
                    child_label = f"{child_label} (parent)"
                child_notes.append((child_label, child.note.strip()))

            if child_notes:
                t.append("\nChild Task Notes\n", style="dim")
                for i, (child_label, child_note) in enumerate(child_notes):
                    t.append(f"[{child_label}]\n", style=f"bold {_BLUE}")
                    t.append(self._format_notes_for_sidebar(child_note), style=_KHAKI)
                    if i < len(child_notes) - 1:
                        t.append("\n\n", style="dim")
        # Threshold
        if step.has_threshold():
            parts: list[str] = []
            if step.threshold_upper:
                parts.append(f"Upper \u2264 {step.threshold_upper}")
            if step.threshold_lower:
                parts.append(f"Lower \u2265 {step.threshold_lower}")
            t.append("\nThreshold\n", style="dim")
            t.append("\n".join(parts), style=_TEAL)
        if step.manual_pass_fail:
            t.append("\nBoolean Check\n", style="dim")
            t.append("Operator decides PASS or FAIL", style=_TEAL)
        if step.requires_text_input:
            t.append("\nText Input Required\n", style="dim")
            t.append("Operator must enter text before completion", style=_TEAL)
            if step.captured_text_input.strip():
                t.append("\nCaptured Input\n", style="dim")
                t.append(step.captured_text_input, style=_KHAKI)
        if step.linked_process_path and self._process.kind == "work_quest":
            link_name = Path(step.linked_process_path).name
            t.append("\nLinked Process\n", style="dim")
            t.append(link_name, style=_BLUE)
        info.update(t)
        self._refresh_focus_cursor_state()

    def _refresh_focus_cursor_state(self) -> None:
        tree = self.query_one("#process_tree", Tree)
        tree.remove_class("cursor-started")
        tree.remove_class("cursor-paused")
        tree.remove_class("cursor-pending")
        tree.remove_class("cursor-failed")

        if self._mode != "run" or not self._process:
            return

        node = tree.cursor_node
        if node is None or node.data is None:
            return

        step = self._process.steps[node.data]
        if step.started and not step.completed:
            if step.paused:
                tree.add_class("cursor-paused")
            else:
                tree.add_class("cursor-started")
        elif step.completed and step.result == "FAIL":
            tree.add_class("cursor-failed")
        elif not step.completed:
            tree.add_class("cursor-pending")

    # ── Run-mode bindings ─────────────────────────────────────────────────────
    def _work_quest_actions_locked(self) -> bool:
        if not self._process or self._process.kind != "work_quest":
            return False
        if self._process.clocked_in:
            return False
        self.notify("Clock in to modify work quest tasks.", severity="warning")
        return True

    def action_complete_step(self) -> None:
        if self._mode != "run" or not self._process:
            return
        if self._work_quest_actions_locked():
            return
        tree = self.query_one("#process_tree", Tree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return
        step_idx = node.data
        step     = self._process.steps[step_idx]

        # Parent steps with children are fully derived from child state.
        if self._process.has_children(step_idx):
            return

        if step.completed:
            return

        if self._process.kind == "work_quest" and step.linked_process_path.strip():
            linked_done, resolved_path = self._linked_process_status(step)
            if resolved_path is not None and str(resolved_path) != step.linked_process_path:
                step.linked_process_path = str(resolved_path)
                save_process(self._process, self._proc_path)
            if linked_done:
                self.notify(
                    "This task is linked and auto-completes when the linked process is done.",
                    severity="information",
                )
            else:
                self.notify(
                    "Complete the linked process first. This task auto-completes.",
                    severity="warning",
                )
            return

        # Work quest flow: first right starts, second right completes.
        if self._process.kind == "work_quest" and not step.started:
            active_idx = self._active_step_idx(exclude_idx=step_idx)
            if active_idx is not None:
                self.notify("You must pause a task in order to do a new one.", severity="warning")
                return
            step.started = True
            step.paused = False
            now_iso = datetime.now().isoformat()
            step.started_at = step.started_at or now_iso
            step.active_since = now_iso
            self._sync_parent_states_from_children()
            save_process(self._process, self._proc_path)
            self._rebuild_proc_tree()
            self._refresh_run_sidebar()
            self._refresh_status()
            self._update_step_info()
            return

        if step.requires_text_input:
            self._pending_text_idx = step_idx
            self.push_screen(
                RequiredTextScreen(step.label),
                callback=self._on_required_text,
            )
        elif step.manual_pass_fail:
            self._pending_manual_idx = step_idx
            self.push_screen(
                ManualResultScreen(step.label),
                callback=self._on_manual_result,
            )
        elif step.has_threshold():
            self._pending_thresh_idx = step_idx
            self.push_screen(
                ThresholdScreen(step.label, step.threshold_upper, step.threshold_lower),
                callback=self._on_threshold_result,
            )
        else:
            self._do_complete(step_idx)

    def _on_required_text(self, entered_text: str | None) -> None:
        if self._pending_text_idx < 0:
            return
        step_idx = self._pending_text_idx
        self._pending_text_idx = -1
        if entered_text is None:
            return
        text = entered_text.strip()
        if not text:
            self.notify("Text entry is required for this step.", severity="warning")
            return

        step = self._process.steps[step_idx]
        step.captured_text_input = text

        if step.manual_pass_fail:
            self._pending_manual_idx = step_idx
            self.push_screen(
                ManualResultScreen(step.label),
                callback=self._on_manual_result,
            )
        elif step.has_threshold():
            self._pending_thresh_idx = step_idx
            self.push_screen(
                ThresholdScreen(step.label, step.threshold_upper, step.threshold_lower),
                callback=self._on_threshold_result,
            )
        else:
            self._do_complete(step_idx)

    def _on_manual_result(self, result: str | None) -> None:
        if self._pending_manual_idx < 0:
            return
        step_idx = self._pending_manual_idx
        self._pending_manual_idx = -1
        if result is None:
            return
        if result not in ("PASS", "FAIL"):
            return
        self._do_complete(step_idx, result=result)

    def _on_threshold_result(self, value_str: str | None) -> None:
        if value_str is None or self._pending_thresh_idx < 0:
            return
        step_idx = self._pending_thresh_idx
        self._pending_thresh_idx = -1
        step     = self._process.steps[step_idx]
        try:
            value = float(value_str)
        except ValueError:
            return

        try:
            ut = float(step.threshold_upper) if step.threshold_upper else None
        except ValueError:
            ut = None
        try:
            lt = float(step.threshold_lower) if step.threshold_lower else None
        except ValueError:
            lt = None

        passed = (ut is None or value <= ut) and (lt is None or value >= lt)
        result = "PASS" if passed else "FAIL"
        sev    = "information" if passed else "warning"
        self._do_complete(step_idx, result=result)

    def _do_complete(self, step_idx: int, result: str = "") -> None:
        proc = self._process
        step = proc.steps[step_idx]
        now = datetime.now()

        if proc.kind == "work_quest" and not step.started:
            active_idx = self._active_step_idx(exclude_idx=step_idx)
            if active_idx is not None:
                self.notify("You must pause a task in order to do a new one.", severity="warning")
                return
            step.started = True
            step.paused = False
            step.started_at = step.started_at or now.isoformat()
            step.active_since = step.active_since or now.isoformat()

        if proc.kind == "work_quest" and step.active_since:
            self._accumulate_active_minutes(step_idx, now)

        step.completed    = True
        step.completed_at = now.isoformat()
        step.paused       = False
        step.active_since = ""
        step.result       = result

        self._sync_parent_states_from_children()

        # Check if the whole process is done
        if proc.is_fully_complete() and not proc.completed:
            proc.completed    = True
            proc.completed_at = now.isoformat()
            self._mark_complete_file()

        next_idx = self._next_completable_run_idx(after_idx=step_idx)

        save_process(proc, self._proc_path)
        self._rebuild_proc_tree()
        self._refresh_run_sidebar()
        self._refresh_status()
        if next_idx is not None:
            self._move_run_cursor_to(next_idx)
        else:
            self._update_step_info()

    def action_uncomplete_step(self) -> None:
        if self._mode != "run" or not self._process:
            return
        if self._work_quest_actions_locked():
            return
        tree = self.query_one("#process_tree", Tree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return
        step_idx = node.data
        proc     = self._process
        step     = proc.steps[step_idx]

        # Parent steps with children are fully derived from child state.
        if proc.has_children(step_idx):
            return

        can_revert_started = proc.kind == "work_quest" and step.started and not step.completed
        if not step.completed and not can_revert_started:
            return

        # Revert to "not even started".
        step.started      = False
        step.started_at   = ""
        step.paused       = False
        step.active_since = ""
        step.completed    = False
        step.completed_at = ""
        step.result       = ""
        step.duration_minutes = 0
        step.duration_seconds = 0
        step.captured_text_input = ""

        self._sync_parent_states_from_children()

        if proc.completed:
            proc.completed    = False
            proc.completed_at = ""
            self._unmark_complete_file()

        save_process(proc, self._proc_path)
        self._rebuild_proc_tree()
        self._refresh_run_sidebar()
        self._refresh_status()
        self._update_step_info()

    def action_note_step(self) -> None:
        if self._mode != "run" or not self._process:
            return
        if self._work_quest_actions_locked():
            return
        tree = self.query_one("#process_tree", Tree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return
        step_idx = node.data
        self.push_screen(
            NoteScreen(current_note=self._process.steps[step_idx].note),
            callback=lambda note: self._on_note_result(step_idx, note),
        )

    def action_pause_step(self) -> None:
        if self._mode != "run" or not self._process or self._process.kind != "work_quest":
            return
        if self._work_quest_actions_locked():
            return
        tree = self.query_one("#process_tree", Tree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return

        step_idx = node.data
        if self._process.has_children(step_idx):
            for child_idx, child in self._process.descendants_of(step_idx):
                if self._process.has_children(child_idx):
                    continue
                if child.started and not child.completed:
                    step_idx = child_idx
                    break

        step = self._process.steps[step_idx]
        if not step.started or step.completed:
            return

        now = datetime.now()
        if step.paused:
            active_idx = self._active_step_idx(exclude_idx=step_idx)
            if active_idx is not None:
                self.notify("You must pause a task in order to do a new one.", severity="warning")
                return
            step.paused = False
            step.active_since = now.isoformat()
        else:
            self._accumulate_active_minutes(step_idx, now)
            step.paused = True

        self._sync_parent_states_from_children()
        save_process(self._process, self._proc_path)
        self._rebuild_proc_tree()
        self._refresh_run_sidebar()
        self._refresh_status()
        self._update_step_info()

    def _focused_run_idx(self) -> int | None:
        node = self.query_one("#process_tree", Tree).cursor_node
        return None if (node is None or node.data is None) else node.data

    def _current_linked_process_path(self) -> Path | None:
        if self._mode != "run" or not self._process or self._process.kind != "work_quest":
            return None
        step_idx = self._focused_run_idx()
        if step_idx is None:
            return None
        raw = self._process.steps[step_idx].linked_process_path.strip()
        if not raw:
            return None
        step = self._process.steps[step_idx]
        _, resolved_path = self._linked_process_status(step)
        return resolved_path or Path(raw)

    def _linked_process_status(self, step: Step) -> tuple[bool, Path | None]:
        raw = step.linked_process_path.strip()
        if not raw:
            return (False, None)

        linked_path = Path(raw)
        candidates: list[Path] = [linked_path]
        if "#COMPLETE" not in linked_path.stem:
            candidates.append(linked_path.with_name(f"{linked_path.stem}#COMPLETE{linked_path.suffix}"))

        existing: Path | None = None
        for cand in candidates:
            if cand.exists():
                existing = cand
                break
        if existing is None:
            return (False, None)

        if "#COMPLETE" in existing.name:
            return (True, existing)

        try:
            linked_proc = load_process(existing)
        except OSError:
            return (False, existing)
        return (linked_proc.completed or linked_proc.is_fully_complete(), existing)

    def _auto_complete_linked_task(self, step_idx: int) -> bool:
        if not self._process or self._process.kind != "work_quest":
            return False
        if step_idx < 0 or step_idx >= len(self._process.steps):
            return False

        step = self._process.steps[step_idx]
        if not step.linked_process_path.strip() or step.completed or not step.started:
            return False

        linked_done, resolved_path = self._linked_process_status(step)
        if resolved_path is not None and str(resolved_path) != step.linked_process_path:
            step.linked_process_path = str(resolved_path)
        if not linked_done:
            return False

        self._do_complete(step_idx)
        return True

    def action_run_linked_process(self) -> None:
        link_path = self._current_linked_process_path()
        if link_path is None or not self._process or not self._proc_path:
            return
        if self._work_quest_actions_locked():
            return
        if not link_path.exists() or link_path.suffix != ".prcss":
            self.notify("Linked process file is missing.", severity="error")
            return

        step_idx = self._focused_run_idx()
        if step_idx is None:
            return

        step = self._process.steps[step_idx]

        # Keep the same in-progress blocking behavior: no other active task may be running.
        active_idx = self._active_step_idx(exclude_idx=step_idx)
        if active_idx is not None:
            self.notify("Pause the active task before running a linked process.", severity="warning")
            return

        # Edge case rule: launching from a paused task is not allowed.
        if step.started and not step.completed and step.paused:
            self.notify("Unpause this task before running its linked process.", severity="warning")
            return

        # Linked templates follow the normal run flow: prompt for run ID and spawn an instance.
        try:
            linked_proc = load_process(link_path)
        except OSError:
            self.notify("Linked process file is missing.", severity="error")
            return

        if (
            linked_proc.kind == "process"
            and linked_proc.spawn_instances
            and link_path.suffix == ".prcss"
            and "#" not in link_path.stem
        ):
            self.push_screen(
                RunIDScreen(link_path.stem),
                callback=lambda run_id: self._launch_linked_template_instance(step_idx, link_path, run_id),
            )
            return

        self._launch_linked_process_file(step_idx, link_path)

    def _launch_linked_template_instance(self, step_idx: int, template_path: Path, run_id: str | None) -> None:
        if run_id is None or not self._process or not self._proc_path:
            return

        try:
            instance_path = create_process_instance(template_path, run_id)
        except OSError:
            self.notify("Could not create process instance.", severity="error")
            return

        self._process.steps[step_idx].linked_process_path = str(instance_path)
        save_process(self._process, self._proc_path)
        self.notify(
            f"New run: {instance_path.name}",
            title="Process Instance Created",
            severity="information",
        )
        self._launch_linked_process_file(step_idx, instance_path)

    def _launch_linked_process_file(self, step_idx: int, link_path: Path) -> None:
        if not self._process or not self._proc_path:
            return

        step = self._process.steps[step_idx]
        now = datetime.now()
        now_iso = now.isoformat()
        if not step.started:
            step.started = True
            step.started_at = step.started_at or now_iso
        if not step.active_since:
            step.active_since = now_iso
        step.completed = False
        step.completed_at = ""
        step.paused = False
        self._sync_parent_states_from_children()

        # Persist current work quest state before switching context.
        save_process(self._process, self._proc_path)
        self._return_wq_path = self._proc_path
        self._return_wq_step_idx = step_idx
        self._open_process_file(link_path)
        self._focus_first_incomplete_run_step()

    def action_back_to_work_quest(self) -> None:
        if self._return_wq_path is None:
            return
        if not self._return_wq_path.exists():
            self.notify("Original work quest file is missing.", severity="error")
            self._clear_work_quest_return_context()
            return

        target_path = self._return_wq_path
        target_idx = self._return_wq_step_idx
        self._clear_work_quest_return_context()
        self._open_process_file(target_path)
        if target_idx is not None:
            if self._auto_complete_linked_task(target_idx):
                self.notify("Linked process complete. Task auto-completed.", severity="information")
            self._move_run_cursor_to(target_idx)

    def _on_note_result(self, step_idx: int, notes_text: str | None) -> None:
        if notes_text is None:
            return
        step = self._process.steps[step_idx]
        step.note = self._merged_instance_note_text(step_idx, notes_text)

        save_process(self._process, self._proc_path)
        self._rebuild_proc_tree()
        self._update_step_info()

    def _merged_instance_note_text(self, step_idx: int, notes_text: str) -> str:
        """Preserve template notes and append instance-only notes for spawned runs."""
        if not self._proc_path or self._proc_path.suffix != ".prcss" or "#" not in self._proc_path.stem:
            return notes_text

        base_path = self._root_template_path(self._proc_path)
        if base_path is None:
            return notes_text

        try:
            base_proc = load_process(base_path)
        except OSError:
            return notes_text

        if base_proc.kind != "process" or not base_proc.spawn_instances:
            return notes_text
        if step_idx < 0 or step_idx >= len(base_proc.steps):
            return notes_text

        base_note = base_proc.steps[step_idx].note.strip()
        if not base_note:
            return notes_text

        base_lines = [line for line in base_note.splitlines() if line.strip()]
        entered_lines = [line for line in notes_text.splitlines() if line.strip()]
        instance_only_lines = [line for line in entered_lines if line not in base_lines]
        merged_lines = base_lines + instance_only_lines
        return "\n".join(merged_lines)

    def _move_run_cursor_to(self, target_idx: int) -> None:
        self.call_after_refresh(self._do_move_run_cursor, target_idx)

    def _next_completable_run_idx(self, after_idx: int) -> int | None:
        if not self._process or not self._process.steps:
            return None
        proc = self._process

        def _is_completable(idx: int) -> bool:
            return not proc.steps[idx].completed and not proc.has_children(idx)

        for idx in range(after_idx + 1, len(proc.steps)):
            if _is_completable(idx):
                return idx
        for idx in range(0, after_idx + 1):
            if _is_completable(idx):
                return idx
        return None

    def _focus_first_incomplete_run_step(self) -> None:
        if not self._process:
            return
        proc = self._process

        # Prefer first incomplete actionable step (leaf), fallback to first incomplete node.
        target_idx: int | None = None
        for idx, step in enumerate(proc.steps):
            if step.completed:
                continue
            if not proc.has_children(idx):
                target_idx = idx
                break
            if target_idx is None:
                target_idx = idx

        if target_idx is not None:
            self._move_run_cursor_to(target_idx)

    def _do_move_run_cursor(self, target_idx: int) -> None:
        tree = self.query_one("#process_tree", Tree)

        def _find(node) -> bool:
            if node.data == target_idx:
                tree.move_cursor(node)
                return True
            for child in node.children:
                if _find(child):
                    return True
            return False

        _find(tree.root)
        tree.focus()

    # ── File rename helpers ───────────────────────────────────────────────────
    def _mark_complete_file(self) -> None:
        if not self._proc_path or "#COMPLETE" in self._proc_path.name:
            return
        new_name = f"{self._proc_path.stem}#COMPLETE{self._proc_path.suffix}"
        new_path = self._proc_path.parent / new_name
        try:
            self._proc_path.rename(new_path)
            self._proc_path = new_path
            save_session(new_path.parent, new_path.name)
        except OSError:
            pass

    def _unmark_complete_file(self) -> None:
        if not self._proc_path or "#COMPLETE" not in self._proc_path.name:
            return
        new_name = self._proc_path.name.replace("#COMPLETE", "")
        new_path = self._proc_path.parent / new_name
        try:
            self._proc_path.rename(new_path)
            self._proc_path = new_path
            save_session(new_path.parent, new_path.name)
        except OSError:
            pass

    # ── Builder actions ───────────────────────────────────────────────────────
    def _rebuild_builder_tree(self) -> None:
        if not self._build_proc:
            return
        proc = self._build_proc
        tree = self.query_one("#builder_tree", Tree)
        tree.reset(Text(proc.name, style=f"bold {_SALMON}"))
        tree.root.data = None

        stack: list[tuple[int, object]] = [(0, tree.root)]
        for idx, step in enumerate(proc.steps):
            while stack and stack[-1][0] >= step.level:
                stack.pop()
            parent_node = stack[-1][1] if stack else tree.root
            number_prefix = self._step_number(proc, idx) if proc.kind == "process" else ""
            if proc.has_children(idx):
                node = parent_node.add(
                    _builder_label(step, number_prefix=number_prefix),
                    data=idx,
                    expand=True,
                )
                stack.append((step.level, node))
            else:
                parent_node.add_leaf(_builder_label(step, number_prefix=number_prefix), data=idx)

        tree.root.expand()

    def _focused_build_idx(self) -> int | None:
        node = self.query_one("#builder_tree", Tree).cursor_node
        return None if (node is None or node.data is None) else node.data

    def action_link_process(self) -> None:
        if self._mode != "build" or not self._build_proc or self._build_proc.kind != "work_quest":
            return
        step_idx = self._focused_build_idx()
        if step_idx is None:
            self.notify("Select a task or sub task first.", severity="warning")
            return

        root = Path.home()
        self.push_screen(
            FilePickerScreen("open_prcss", start=root),
            callback=lambda path: self._on_link_process_selected(step_idx, path),
        )

    def _on_link_process_selected(self, step_idx: int, path: Path | None) -> None:
        if path is None or not self._build_proc:
            return
        if path.suffix != ".prcss":
            self.notify("Select a process file (.prcss).", severity="warning")
            return

        self._build_proc.steps[step_idx].linked_process_path = str(path)
        self._rebuild_builder_tree()
        self._move_builder_cursor_to(step_idx)
        self.notify(f"Linked: {path.name}", severity="information")

    def _reset_carried_step_state(self, step: Step) -> Step:
        clone = copy.deepcopy(step)
        clone.started = False
        clone.started_at = ""
        clone.paused = False
        clone.active_since = ""
        clone.completed = False
        clone.completed_at = ""
        clone.duration_minutes = 0
        clone.duration_seconds = 0
        clone.captured_text_input = ""
        clone.result = ""
        return clone

    def _steps_to_forest(self, steps: list[Step]) -> list[dict[str, object]]:
        forest: list[dict[str, object]] = []
        stack: list[dict[str, object]] = []
        for step in steps:
            node = {"step": copy.deepcopy(step), "children": []}
            while stack and (stack[-1]["step"]).level >= step.level:
                stack.pop()
            if stack:
                (stack[-1]["children"]).append(node)
            else:
                forest.append(node)
            stack.append(node)
        return forest

    def _merge_forest_by_parent_name(self, destination: list[dict[str, object]], incoming: list[dict[str, object]]) -> None:
        for node in incoming:
            incoming_step = node["step"]
            incoming_children = node["children"]

            # Parent de-duplication: if a same-name node already exists at this sibling level,
            # fold incoming children into the existing node instead of adding another parent node.
            matching_parent = None
            if incoming_children:
                for existing in destination:
                    existing_step = existing["step"]
                    if existing_step.label == incoming_step.label:
                        matching_parent = existing
                        break

            if matching_parent is not None:
                self._merge_forest_by_parent_name(matching_parent["children"], incoming_children)
                continue

            destination.append(copy.deepcopy(node))

    def _flatten_forest(self, forest: list[dict[str, object]], level: int = 1) -> list[Step]:
        flat: list[Step] = []
        for node in forest:
            step = node["step"]
            step.level = level
            flat.append(step)
            flat.extend(self._flatten_forest(node["children"], level + 1))
        return flat

    def action_carry_over(self) -> None:
        if self._mode != "build" or not self._build_proc or self._build_proc.kind != "work_quest":
            return
        self.push_screen(
            FilePickerScreen("open_wrkqst", start=Path.home()),
            callback=self._on_carry_over_selected,
        )

    def _on_carry_over_selected(self, destination_path: Path | None) -> None:
        if destination_path is None or not self._build_proc:
            return
        if destination_path.suffix != ".wrkqst":
            self.notify("Select a work quest file (.wrkqst).", severity="warning")
            return
        if self._build_path and destination_path == self._build_path:
            self.notify("Choose a different destination work quest.", severity="warning")
            return

        try:
            destination_proc = load_process(destination_path)
        except OSError:
            self.notify("Could not load selected work quest.", severity="error")
            return

        if destination_proc.kind != "work_quest":
            self.notify("Selected file is not a work quest.", severity="warning")
            return

        total_steps = len(self._build_proc.steps)
        if total_steps == 0:
            self.notify("Current work quest has no tasks to carry over.", severity="information")
            return

        children_map: dict[int, list[int]] = {i: [] for i in range(total_steps)}
        stack: list[int] = []
        for idx, step in enumerate(self._build_proc.steps):
            while stack and self._build_proc.steps[stack[-1]].level >= step.level:
                stack.pop()
            if stack:
                children_map[stack[-1]].append(idx)
            stack.append(idx)

        keep_in_source = [False] * total_steps
        carry_to_target = [False] * total_steps
        for idx in range(total_steps - 1, -1, -1):
            step = self._build_proc.steps[idx]
            child_idxs = children_map[idx]
            any_kept_child = any(keep_in_source[child_idx] for child_idx in child_idxs)
            any_carried_child = any(carry_to_target[child_idx] for child_idx in child_idxs)

            keep_in_source[idx] = step.completed or any_kept_child
            carry_to_target[idx] = (not step.completed) or any_carried_child

        carried_steps = [
            self._reset_carried_step_state(self._build_proc.steps[idx])
            for idx in range(total_steps)
            if carry_to_target[idx]
        ]
        carried_leaf_count = sum(
            1
            for idx in range(total_steps)
            if carry_to_target[idx] and not children_map[idx] and not self._build_proc.steps[idx].completed
        )

        if not carried_steps:
            self.notify("No unfinished tasks found to carry over.", severity="information")
            return

        source_proc_updated = copy.deepcopy(self._build_proc)
        source_proc_updated.steps = [self._build_proc.steps[idx] for idx in range(total_steps) if keep_in_source[idx]]
        self._sync_parent_states_for_process(source_proc_updated)
        source_proc_updated.completed = source_proc_updated.is_fully_complete()
        if not source_proc_updated.completed:
            source_proc_updated.completed_at = ""

        destination_proc_updated = copy.deepcopy(destination_proc)
        destination_forest = self._steps_to_forest(destination_proc_updated.steps)
        carried_forest = self._steps_to_forest(carried_steps)
        self._merge_forest_by_parent_name(destination_forest, carried_forest)
        destination_proc_updated.steps = self._flatten_forest(destination_forest)
        self._sync_parent_states_for_process(destination_proc_updated)
        destination_proc_updated.completed = destination_proc_updated.is_fully_complete()
        if not destination_proc_updated.completed:
            destination_proc_updated.completed_at = ""

        try:
            save_process(destination_proc_updated, destination_path)
        except OSError:
            self.notify("Carry over failed while updating destination work quest.", severity="error")
            return

        if self._build_path:
            try:
                save_process(source_proc_updated, self._build_path)
            except OSError:
                self.notify(
                    "Destination updated, but current source work quest could not be saved.",
                    severity="error",
                )
                return

        self._build_proc = source_proc_updated

        self._rebuild_builder_tree()
        self.query_one("#builder_tree", Tree).focus()
        self.notify(
            f"Carried over {carried_leaf_count} unfinished tasks to {destination_path.name}.",
            severity="information",
        )

    def _move_builder_cursor_to(self, target_idx: int) -> None:
        """Schedule a cursor move to the node with data==target_idx after the tree redraws."""
        self.call_after_refresh(self._do_move_builder_cursor, target_idx)

    def _do_move_builder_cursor(self, target_idx: int) -> None:
        tree = self.query_one("#builder_tree", Tree)

        def _find(node) -> bool:
            if node.data == target_idx:
                tree.move_cursor(node)
                return True
            for child in node.children:
                if _find(child):
                    return True
            return False

        _find(tree.root)
        tree.focus()

    def action_add_step(self) -> None:
        if self._mode != "build":
            return
        item_term, _ = self._build_terms()
        self.push_screen(
            StepScreen(
                title=f"Add Top-Level {item_term}",
                allow_thresholds=self._build_proc is not None and self._build_proc.kind == "process",
                allow_main_quest=self._build_proc is not None and self._build_proc.kind == "work_quest",
                multi_mode=True,
            ),
            callback=self._on_add_step,
        )

    def _on_add_step(self, data: dict | list[dict] | None) -> None:
        if data is None or not self._build_proc:
            return
        items = data if isinstance(data, list) else [data]
        cur_idx = self._focused_build_idx()
        if cur_idx is not None:
            top_idx = cur_idx
            while top_idx > 0 and self._build_proc.steps[top_idx].level > 1:
                parent_idx = self._build_proc.parent_of(top_idx)
                if parent_idx is None:
                    break
                top_idx = parent_idx
            insert_at = self._build_proc.last_descendant_idx(top_idx) + 1
        else:
            insert_at = len(self._build_proc.steps)
        for offset, item in enumerate(items):
            self._build_proc.steps.insert(insert_at + offset, Step(
                label=item["label"], level=1,
                threshold_upper=item["threshold_upper"],
                threshold_lower=item["threshold_lower"],
                note=str(item.get("note", "")),
                main_quest=bool(item.get("main_quest", False)),
                manual_pass_fail=bool(item.get("manual_pass_fail", False)),
                requires_text_input=bool(item.get("requires_text_input", False)),
            ))
        self._rebuild_builder_tree()
        self.query_one("#builder_tree", Tree).focus()

    def action_add_sub_step(self) -> None:
        if self._mode != "build":
            return
        _, sub_item_term = self._build_terms()
        cur_idx = self._focused_build_idx()
        parent_label = ""
        if cur_idx is not None and self._build_proc is not None:
            parent = self._build_proc.steps[cur_idx]
            number_prefix = self._step_number(self._build_proc, cur_idx) if self._build_proc.kind == "process" else ""
            parent_label = f"{number_prefix} {parent.label}" if number_prefix else parent.label
        self.push_screen(
            StepScreen(
                title=f"Add {sub_item_term}",
                allow_thresholds=self._build_proc is not None and self._build_proc.kind == "process",
                allow_main_quest=False,
                multi_mode=True,
                parent_label=parent_label,
            ),
            callback=self._on_add_sub,
        )

    def _on_add_sub(self, data: dict | list[dict] | None) -> None:
        if data is None or not self._build_proc:
            return
        items = data if isinstance(data, list) else [data]
        cur_idx = self._focused_build_idx()
        if cur_idx is None:
            return
        proc = self._build_proc
        step = proc.steps[cur_idx]
        insert_at = proc.last_descendant_idx(cur_idx) + 1
        for offset, item in enumerate(items):
            proc.steps.insert(insert_at + offset, Step(
                label=item["label"], level=step.level + 1,
                threshold_upper=item["threshold_upper"],
                threshold_lower=item["threshold_lower"],
                note=str(item.get("note", "")),
                main_quest=False,
                manual_pass_fail=bool(item.get("manual_pass_fail", False)),
                requires_text_input=bool(item.get("requires_text_input", False)),
            ))
        self._rebuild_builder_tree()
        self.query_one("#builder_tree", Tree).focus()

    def action_edit_step(self) -> None:
        if self._mode != "build":
            return
        cur_idx = self._focused_build_idx()
        if cur_idx is None:
            return
        step = self._build_proc.steps[cur_idx]
        item_term, sub_item_term = self._build_terms()
        edit_term = sub_item_term if step.level > 1 else item_term
        self.push_screen(
            StepScreen(
                existing=step,
                title=f"Edit {edit_term}",
                allow_thresholds=self._build_proc.kind == "process",
                allow_main_quest=self._build_proc.kind == "work_quest" and step.level == 1,
            ),
            callback=lambda d: self._on_edit_step(cur_idx, d),
        )

    def _on_edit_step(self, step_idx: int, data: dict | None) -> None:
        if data is None or not self._build_proc:
            return
        step = self._build_proc.steps[step_idx]
        step.label           = data["label"]
        step.threshold_upper = data["threshold_upper"]
        step.threshold_lower = data["threshold_lower"]
        step.note = str(data.get("note", ""))
        step.main_quest = bool(data.get("main_quest", False)) if step.level == 1 else False
        step.manual_pass_fail = bool(data.get("manual_pass_fail", False))
        step.requires_text_input = bool(data.get("requires_text_input", False))
        self._rebuild_builder_tree()

    def action_delete_step(self) -> None:
        if self._mode != "build":
            return
        cur_idx = self._focused_build_idx()
        if cur_idx is None:
            return
        proc = self._build_proc
        end = proc.last_descendant_idx(cur_idx) + 1
        del proc.steps[cur_idx:end]
        self._rebuild_builder_tree()
        self.query_one("#builder_tree", Tree).focus()

    def action_shift_step_up(self) -> None:
        if self._mode != "build" or not self._build_proc:
            return
        if self._build_proc.kind != "process":
            return
        cur_idx = self._focused_build_idx()
        if cur_idx is None:
            return
        proc = self._build_proc
        cur_level = proc.steps[cur_idx].level

        # Walk backwards past deeper steps to find the previous sibling.
        prev_sib_idx = cur_idx - 1
        while prev_sib_idx >= 0 and proc.steps[prev_sib_idx].level > cur_level:
            prev_sib_idx -= 1

        if prev_sib_idx < 0 or proc.steps[prev_sib_idx].level != cur_level:
            return  # no previous sibling at the same level

        cur_end = proc.subtree_end_exclusive(cur_idx)
        cur_subtree  = proc.steps[cur_idx:cur_end]
        prev_subtree = proc.steps[prev_sib_idx:cur_idx]
        proc.steps[prev_sib_idx:cur_end] = cur_subtree + prev_subtree
        new_idx = prev_sib_idx
        self._rebuild_builder_tree()
        self._move_builder_cursor_to(new_idx)

    def action_shift_step_down(self) -> None:
        if self._mode != "build" or not self._build_proc:
            return
        if self._build_proc.kind != "process":
            return
        cur_idx = self._focused_build_idx()
        if cur_idx is None:
            return
        proc = self._build_proc
        cur_level = proc.steps[cur_idx].level

        cur_end = proc.subtree_end_exclusive(cur_idx)
        if cur_end >= len(proc.steps):
            return  # nothing below
        if proc.steps[cur_end].level != cur_level:
            return  # next step is not at the same level (not a sibling)

        next_sib_idx = cur_end
        next_end = proc.subtree_end_exclusive(next_sib_idx)
        cur_subtree  = proc.steps[cur_idx:cur_end]
        next_subtree = proc.steps[next_sib_idx:next_end]
        new_idx = cur_idx + len(next_subtree)
        proc.steps[cur_idx:next_end] = next_subtree + cur_subtree
        self._rebuild_builder_tree()
        self._move_builder_cursor_to(new_idx)

    def action_save_build(self) -> None:
        if self._mode != "build" or not self._build_proc:
            return
        name = self.query_one("#build_name_inp", Input).value.strip()
        if name:
            self._build_proc.name = name
        if self._build_path:
            if self._build_root_path and self._build_root_path != self._build_path:
                self.push_screen(
                    ConfirmScreen(
                        f"Apply these changes to the root process too?\n\nRoot: {self._build_root_path.name}"
                    ),
                    callback=self._on_save_root_confirmed,
                )
                return
            # Editing an existing file — save in place
            self._do_save_build(self._build_path)
        else:
            # New process — ask where to save
            start = self._build_dir or Path.home()
            suggested = sanitize_filename_for(self._build_proc.name, self._build_proc.kind)
            ext = ".wrkqst" if self._build_proc.kind == "work_quest" else ".prcss"
            self.push_screen(
                FilePickerScreen("save", start=start, filename=suggested, save_ext=ext),
                callback=self._on_save_dialog,
            )

    def _on_save_root_confirmed(self, confirmed: bool | None) -> None:
        if not self._build_proc or not self._build_path:
            return

        current_path = self._build_path
        root_path = self._build_root_path
        self._do_save_build(current_path)

        # User selected Cancel/No-root: keep normal save behavior (instance only).
        if not confirmed or root_path is None:
            return

        try:
            save_process(self._process_for_save(self._build_proc, root_path), root_path)
            self.notify(f"Updated root template: {root_path.name}", severity="information")
        except OSError:
            self.notify("Could not update root template.", severity="error")

    def _reset_process_state(self, proc: Process) -> None:
        proc.completed = False
        proc.completed_at = ""
        proc.clocked_in = False
        proc.clock_active_since = ""
        proc.clock_events.clear()
        for step in proc.steps:
            step.started = False
            step.started_at = ""
            step.paused = False
            step.active_since = ""
            step.completed = False
            step.completed_at = ""
            step.duration_minutes = 0
            step.duration_seconds = 0
            step.captured_text_input = ""
            step.result = ""

    def _on_save_dialog(self, path: Path | None) -> None:
        if path is None:
            return
        self._build_path = path
        self._build_dir  = path.parent
        self._do_save_build(path)

    def _is_root_template_save_target(self, proc: Process, save_path: Path) -> bool:
        return (
            proc.kind == "process"
            and proc.spawn_instances
            and save_path.suffix == ".prcss"
            and "#" not in save_path.stem
        )

    def _process_for_save(self, proc: Process, save_path: Path) -> Process:
        if not self._is_root_template_save_target(proc, save_path):
            return proc
        sanitized = copy.deepcopy(proc)
        self._reset_process_state(sanitized)
        return sanitized

    def _do_save_build(self, save_path: Path) -> None:
        try:
            save_process(self._process_for_save(self._build_proc, save_path), save_path)
            save_session(save_path.parent, save_path.name)
            self._proc_path = save_path
            self._process   = self._build_proc
        except OSError:
            return
        self._update_build_file_label()
        self._refresh_status()

    # ── Builder input sync ────────────────────────────────────────────────────
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "build_name_inp" and self._build_proc:
            self._build_proc.name = event.value
            tree = self.query_one("#builder_tree", Tree)
            tree.root.set_label(Text(event.value, style=f"bold {_SALMON}"))

    # ── Directory/file selection ──────────────────────────────────────────────
    def _update_build_file_label(self) -> None:
        label = self.query_one("#build_file_label", Static)
        if self._build_path:
            label_text = Text(self._build_path.name, style=f"bold {_BLUE}")
        else:
            label_text = Text("New (unsaved)", style=f"bold {_GOLD}")

        if self._build_proc and self._build_proc.kind == "process":
            if self._build_path and self._build_path.suffix == ".prcss" and "#" in self._build_path.stem:
                badge = " Instance"
                badge_style = f"bold {_PURPLE}"
                if self._build_root_path:
                    label_text.append(f"  root: {self._build_root_path.name}", style=f"dim {_KHAKI}")
            elif self._build_proc.spawn_instances:
                badge = " Template"
                badge_style = f"bold {_GREEN}"
            else:
                badge = " Unique"
                badge_style = f"bold {_PURPLE}"
            label_text.append(f"{badge}", style=badge_style)

        label.update(label_text)

    # ── Log viewer ────────────────────────────────────────────────────────────
    def _view_log(self, file_path: Path) -> None:
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            return
        log = self.query_one("#log_output", Log)
        log.clear()
        for line in text.splitlines():
            log.write_line(line)
        self.query_one("#content", ContentSwitcher).current = "view_logs"
        log_label = Text("  LOG  ", style="dim")
        log_label.append(file_path.name, style=f"bold {_SALMON}")
        self.query_one("#status_bar", Static).update(log_label)

    def _do_dissolve(self, file_path: Path) -> None:
        try:
            proc     = load_process(file_path)
            log_path = publish_process(proc, file_path)
            sess = load_session()
            if sess and sess[0] == file_path.parent and sess[1] == file_path.name:
                save_session(file_path.parent, "")
            self._set_mode("logs")
            self._view_log(log_path)
            status = Text("  LOG  ", style="dim")
            status.append(log_path.name, style=f"bold {_SALMON}")
            status.append("    PDF  ", style="dim")
            status.append(log_path.name + ".pdf", style=f"bold {_TEAL}")
            self.query_one("#status_bar", Static).update(status)
        except OSError:
            pass

    # ── Tree cursor events ────────────────────────────────────────────────────
    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.tree.id == "process_tree":
            self._update_step_info()
            self.refresh_bindings()

    # ── Binding guards ────────────────────────────────────────────────────────
    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "close_active":
            return self._process is not None
        if action in ("complete_step", "uncomplete_step", "note_step", "pause_step"):
            return self._mode == "run"
        if action == "toggle_clock":
            return self._mode == "run"
        if action in ("add_step", "add_sub_step", "edit_step", "delete_step"):
            return self._mode == "build" and not isinstance(self.focused, Input)
        if action == "link_process":
            return (
                self._mode == "build"
                and not isinstance(self.focused, Input)
                and self._build_proc is not None
                and self._build_proc.kind == "work_quest"
            )
        if action == "carry_over":
            return (
                self._mode == "build"
                and not isinstance(self.focused, Input)
                and self._build_proc is not None
                and self._build_proc.kind == "work_quest"
            )
        if action in ("shift_step_up", "shift_step_down"):
            return (
                self._mode == "build"
                and not isinstance(self.focused, Input)
                and self._build_proc is not None
                and self._build_proc.kind == "process"
            )
        if action == "run_linked_process":
            return self._current_linked_process_path() is not None
        if action == "back_to_work_quest":
            return self._mode == "run" and self._return_wq_path is not None
        if action == "save_build":
            return self._mode == "build"
        return True

    # ── Global back / quit ────────────────────────────────────────────────────
    def action_go_back(self) -> None:
        self._show_home()


"""
VeriTrakk  -  app.py
Full rewrite with clean split-layout UI, modal screens for editing,
toolbar-driven navigation, and CSV-backed data model.
"""
from __future__ import annotations

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
        multi_mode: bool = False,
        parent_label: str = "",
    ) -> None:
        super().__init__()
        self._ex    = existing
        self._title = title
        self._allow_thresholds = allow_thresholds
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
        manual_pf = self.query_one("#step_manual_pf", Switch).value if self._allow_thresholds else False
        requires_text_input = self.query_one("#step_requires_text", Switch).value if self._allow_thresholds else False
        return {
            "label": self.query_one("#step_label", Input).value.strip(),
            "threshold_upper": upper,
            "threshold_lower": lower,
            "target_value": nominal,
            "tolerance_pct": tolerance,
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
            "manual_pass_fail": False,
            "requires_text_input": False,
        }
        self.query_one("#step_label", Input).value = payload.get("label", "")
        if self._allow_thresholds:
            self.query_one("#step_nominal", Input).value = payload.get("target_value", "")
            self.query_one("#step_tolerance", Input).value = payload.get("tolerance_pct", "")
            self.query_one("#step_ut", Input).value = payload.get("threshold_upper", "")
            self.query_one("#step_lt", Input).value = payload.get("threshold_lower", "")
            self.query_one("#step_manual_pf", Switch).value = bool(payload.get("manual_pass_fail", False))
            self.query_one("#step_requires_text", Switch).value = bool(payload.get("requires_text_input", False))

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
        manual_pf = self.query_one("#step_manual_pf", Switch).value if self._allow_thresholds else False
        requires_text_input = self.query_one("#step_requires_text", Switch).value if self._allow_thresholds else False
        self.dismiss({
            "label":           label,
            "threshold_upper": upper,
            "threshold_lower": lower,
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
        self._mode     = mode          # "open" | "open_prcss" | "save" | "logs"
        self._start    = start or Path.home()
        self._filename = filename
        self._save_ext = save_ext
        self._cur_dir: Path = self._start

    def compose(self) -> ComposeResult:
        titles = {
            "open": "Open Process",
            "open_prcss": "Link Process",
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
        if self._mode in ("open", "open_prcss", "logs"):
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
        Binding("n",     "note_step",       "Note",      show=True),
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
    _build_kind:        str           = "process"
    _build_spawn_instances: bool      = True
    _pending_thresh_idx: int           = -1
    _pending_manual_idx: int           = -1
    _pending_text_idx: int             = -1
    _syncing_clock_switch: bool        = False
    _return_wq_path:    Path | None    = None
    _return_wq_step_idx: int | None    = None

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
                    yield Static(
                        " VeriTrakk\n Process Tracking\n Westbound Designs",
                        id="logo",
                    )

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
                        yield Digits("00:00", id="quest_digit")
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
                    yield Tree("New Process", id="builder_tree")

                # logs viewer
                with Vertical(id="view_logs"):
                    yield Log(id="log_output", auto_scroll=False)

        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def on_mount(self) -> None:
        proc_tree = self.query_one("#process_tree", Tree)
        proc_tree.auto_expand = False
        proc_tree.root.expand()
        build_tree = self.query_one("#builder_tree", Tree)
        build_tree.auto_expand = False
        build_tree.root.expand()
        self.set_interval(1, self._tick_clock)
        self._show_home()

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

    def _open_picker(self) -> None:
        start = Path.home()
        self.push_screen(
            FilePickerScreen("open", start=start),
            callback=lambda path: self._load_process(path) if path else None,
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
        else:
            self._build_path = None
            self._build_dir = None
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
            self._open_picker()

    def _resume(self) -> None:
        sess = load_session()
        if not sess:
            return
        directory, file_name = sess
        path = directory / file_name
        if not path.exists():
            return
        self._load_process(path)

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
        if self._is_work_quest_active():
            self._refresh_quest_clock_widgets()
        self._refresh_proc_tree_live()
        self._refresh_status()
        self._update_step_info()

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

    def _sync_parent_states_from_children(self) -> None:
        if not self._process:
            return
        proc = self._process
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

            # Parent run-state is derived from children currently in progress.
            parent.started = any_in_progress
            parent.started_at = min(started_stamps) if (any_in_progress or all_done) and started_stamps else ""
            parent.completed = all_done
            parent.completed_at = max(completed_stamps) if all_done and completed_stamps else ""
            parent.paused = any_in_progress and not any_active
            parent.active_since = ""
            parent.duration_seconds = sum(max(0, child.duration_seconds) for child in child_steps)
            self._sync_duration_minutes(parent)

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
        digit.update(self._format_minutes(self._process.total_clock_minutes()))

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

        now = datetime.now()
        stack: list[tuple[int, object]] = [(0, tree.root)]
        for idx, step in enumerate(proc.steps):
            while stack and stack[-1][0] >= step.level:
                stack.pop()
            parent_node = stack[-1][1] if stack else tree.root
            number_prefix = self._step_number(proc, idx) if proc.kind == "process" else ""

            children = proc.children_of(idx)
            sub_done = sum(1 for _, child in children if child.completed)
            sub_total = len(children)

            if children:
                node = parent_node.add(
                    _step_label(
                        step,
                        number_prefix=number_prefix,
                        show_process_badge=proc.kind == "work_quest",
                        sub_done=sub_done,
                        sub_total=sub_total,
                        live_seconds=self._live_step_seconds(idx, now),
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
                        live_seconds=self._live_step_seconds(idx, now),
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

        def _walk(node) -> None:
            if node.data is not None:
                idx = node.data
                step = proc.steps[idx]
                number_prefix = self._step_number(proc, idx) if proc.kind == "process" else ""
                children = proc.children_of(idx)
                sub_done = sum(1 for _, child in children if child.completed)
                sub_total = len(children)
                node.set_label(
                    _step_label(
                        step,
                        number_prefix=number_prefix,
                        show_process_badge=proc.kind == "work_quest",
                        sub_done=sub_done if children else None,
                        sub_total=sub_total if children else None,
                        live_seconds=self._live_step_seconds(idx, now),
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
            t.append(step.note, style=_KHAKI)
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
    def action_complete_step(self) -> None:
        if self._mode != "run" or not self._process:
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

        if self._process.kind == "work_quest" and not self._process.clocked_in:
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

        save_process(proc, self._proc_path)
        self._rebuild_proc_tree()
        self._refresh_run_sidebar()
        self._refresh_status()
        self._update_step_info()

    def action_uncomplete_step(self) -> None:
        if self._mode != "run" or not self._process:
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
        tree = self.query_one("#process_tree", Tree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return

        step_idx = node.data
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

        # Launching a linked process moves this task into active in-progress state.
        now_iso = datetime.now().isoformat()
        if not step.started:
            step.started = True
            step.started_at = step.started_at or now_iso
        step.completed = False
        step.completed_at = ""
        step.paused = False
        step.active_since = now_iso
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
        step.note = notes_text

        save_process(self._process, self._proc_path)
        self._rebuild_proc_tree()
        self._update_step_info()

    def _move_run_cursor_to(self, target_idx: int) -> None:
        self.call_after_refresh(self._do_move_run_cursor, target_idx)

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
        if path.suffix != ".prcss" or "#" not in path.stem:
            self.notify("Select a process instance file (.prcss with '#').", severity="warning")
            return

        self._build_proc.steps[step_idx].linked_process_path = str(path)
        self._rebuild_builder_tree()
        self._move_builder_cursor_to(step_idx)
        self.notify(f"Linked: {path.name}", severity="information")

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

    def _on_save_dialog(self, path: Path | None) -> None:
        if path is None:
            return
        self._build_path = path
        self._build_dir  = path.parent
        self._do_save_build(path)

    def _do_save_build(self, save_path: Path) -> None:
        try:
            save_process(self._build_proc, save_path)
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
            badge = " Template" if self._build_proc.spawn_instances else " Unique"
            badge_style = f"bold {_GREEN}" if self._build_proc.spawn_instances else f"bold {_PURPLE}"
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


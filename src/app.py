"""
VeriTrakk  -  app.py
Full rewrite with clean split-layout UI, modal screens for editing,
toolbar-driven navigation, and CSV-backed data model.
"""
from __future__ import annotations

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
)

# Brand colors as hex (Rich doesn't know Textual CSS color names)
_SALMON  = "#ffa07a"  # lightsalmon
_GREEN   = "#8fbc8f"  # darkseagreen
_GOLD    = "#daa520"  # goldenrod
_KHAKI   = "#bdb76b"  # darkkhaki
_TEAL    = "#5f9ea0"  # cadetblue
_BLUE    = "#1e90ff"  # dodgerblue


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
    step: Step, *, sub_done: int | None = None, sub_total: int | None = None
) -> Text:
    """Rich Text label for a step node in the run-mode tree."""
    if step.completed:
        if step.result == "PASS":
            t = Text(f"\u2713  {step.label}", style=f"bold {_GREEN}")
            t.append("   PASS", style=f"bold {_GREEN}")
        elif step.result == "FAIL":
            t = Text(f"\u2717  {step.label}", style="bold red")
            t.append("   FAIL", style="bold red")
        else:
            ts = ""
            if step.completed_at:
                try:
                    dt = datetime.fromisoformat(step.completed_at)
                    ts = f"   {dt.strftime('%H:%M')}"
                except ValueError:
                    pass
            t = Text(f"\u2713  {step.label}", style=_GREEN)
            if ts:
                t.append(ts, style=f"dim {_GREEN}")
            if step.duration_minutes > 0:
                h = step.duration_minutes // 60
                m = step.duration_minutes % 60
                t.append(f"   {h:02d}:{m:02d}", style=f"dim {_TEAL}")
    elif step.started:
        t = Text(f"\u25d4  {step.label}", style=f"bold {_BLUE}")
        if sub_done is not None and sub_total:
            t.append(f"  ({sub_done}/{sub_total})", style=f"dim {_KHAKI}")
    else:
        t = Text(f"\u25cb  {step.label}")
        if sub_done is not None and sub_total:
            t.append(f"  ({sub_done}/{sub_total})", style=f"dim {_KHAKI}")
        if step.has_threshold():
            t.append("  \u2299", style=_TEAL)
        if step.note:
            t.append("  \xb7", style=f"dim {_KHAKI}")
    return t


def _builder_label(step: Step) -> Text:
    """Rich Text label for a step node in the builder tree."""
    prefix = "  " if step.level == 2 else ""
    t = Text(f"{prefix}{step.label}")
    extras: list[str] = []
    if step.note:
        extras.append("[N]")
    if step.has_threshold():
        extras.append("[T]")
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
    """Add or edit a note on a step."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_note: str = "") -> None:
        super().__init__()
        self._current = current_note

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_box"):
            yield Static("Add / Edit Note", id="modal_title")
            yield Input(value=self._current, placeholder="Enter note...", id="note_inp")
            with Horizontal(id="modal_btns"):
                yield Button("Save",   variant="primary", id="btn_save")
                yield Button("Clear",  variant="warning", id="btn_clear")
                yield Button("Cancel",                   id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_clear":
            self.dismiss("")
        elif event.button.id == "btn_save":
            self.dismiss(self.query_one("#note_inp", Input).value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


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


class StepScreen(ModalScreen):
    """Add or edit a task: label, optional note, optional thresholds."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, existing: Step | None = None, title: str = "Add Task") -> None:
        super().__init__()
        self._ex    = existing
        self._title = title

    def compose(self) -> ComposeResult:
        ex = self._ex
        with Vertical(id="modal_box"):
            yield Static(self._title, id="modal_title")
            yield Label("Label")
            yield Input(
                value=ex.label if ex else "",
                placeholder="Task name...", id="step_label",
            )
            yield Label("Note  (optional)")
            yield Input(
                value=ex.note if ex else "",
                placeholder="Note...", id="step_note",
            )
            yield Label("Upper Threshold  (optional)")
            yield Input(
                value=ex.threshold_upper if ex else "",
                placeholder="e.g. 5.3", id="step_ut",
            )
            yield Label("Lower Threshold  (optional)")
            yield Input(
                value=ex.threshold_lower if ex else "",
                placeholder="e.g. 4.7", id="step_lt",
            )
            with Horizontal(id="modal_btns"):
                yield Button("Save",   variant="primary", id="btn_save")
                yield Button("Cancel",                   id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_save":
            self._submit()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        label = self.query_one("#step_label", Input).value.strip()
        if not label:
            return
        self.dismiss({
            "label":           label,
            "note":            self.query_one("#step_note", Input).value.strip(),
            "threshold_upper": self.query_one("#step_ut",   Input).value.strip(),
            "threshold_lower": self.query_one("#step_lt",   Input).value.strip(),
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
        self._mode     = mode          # "open" | "save" | "logs"
        self._start    = start or Path.home()
        self._filename = filename
        self._save_ext = save_ext
        self._cur_dir: Path = self._start

    def compose(self) -> ComposeResult:
        titles = {
            "open": "Open Process",
            "save": "Save Process As",
            "logs": "Browse Logs",
        }
        with Vertical(id="fp_box"):
            yield Static(titles[self._mode], id="fp_title")
            yield Static(str(self._start), id="fp_path")
            if self._mode == "open":
                yield ProcessFileTree(self._start, id="fp_tree")
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
        if self._mode in ("open", "logs"):
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


class NewFileTypeScreen(ModalScreen):
    """Choose whether a new file is a process or work quest."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def on_mount(self) -> None:
        # Avoid auto-focusing the first button to prevent harsh focus tint.
        self.app.set_focus(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="new_file_type_box"):
            yield Static("New File Type", id="modal_title")
            yield Static("Choose what you want to create.", id="confirm_msg")
            with Horizontal(id="modal_btns"):
                yield Button("Process (.prcss)", variant="primary", id="btn_proc")
                yield Button("Work Quest (.wrkqst)", variant="success", id="btn_wrkqst")
                yield Button("Cancel", variant="default", id="btn_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_proc":
            self.dismiss("process")
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
        Binding("c",     "toggle_clock",    "Clock In/Out", show=True),
        # Build-mode actions
        Binding("a",      "add_step",     "Add Task", show=False),
        Binding("s",      "add_sub_step", "Add Sub Task",  show=False),
        Binding("e",      "edit_step",    "Edit",     show=False),
        Binding("d",      "delete_step",  "Delete",   show=False),
        Binding("ctrl+s", "save_build",   "Save",     show=False),
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
    _pending_thresh_idx: int           = -1
    _syncing_clock_switch: bool        = False

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
                        yield Button("+ Task",  id="btn_add_step",  variant="success", classes="build_btn")
                        yield Button("+ Sub Task",   id="btn_add_sub",   variant="success", classes="build_btn")
                        yield Button("Edit",    id="btn_edit_step", variant="default", classes="build_btn")
                        yield Button("Delete",  id="btn_del_step",  variant="error",   classes="build_btn")
                        yield Button("Save",    id="btn_save_proc", variant="primary", classes="build_btn")
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
        self.set_interval(30, self._tick_clock)
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
        start = self._build_dir or Path.home()
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
        else:
            self._build_path = None
            default_name = "New Work Quest" if self._build_kind == "work_quest" else "New Process"
            self._build_proc = Process(name=default_name, kind=self._build_kind)

        self.query_one("#build_name_inp", Input).value = self._build_proc.name
        self._rebuild_builder_tree()
        self._update_build_file_label()
        self._switch("side_build", "view_build")
        self._refresh_quest_clock_widgets()
        self._refresh_status()
        self.query_one("#build_name_inp", Input).focus()

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
        if bid == "btn_edit_step":
            self.action_edit_step(); return
        if bid == "btn_del_step":
            self.action_delete_step(); return
        if bid == "btn_save_proc":
            self.action_save_build(); return

    # ── New / Open / Resume / Build flows ─────────────────────────────────────
    def _start_new_process(self) -> None:
        self.push_screen(NewFileTypeScreen(), callback=self._on_new_file_type)

    def _on_new_file_type(self, kind: str | None) -> None:
        if kind is None:
            return
        self._build_kind = kind
        self._build_path = None
        default_name = "New Work Quest" if kind == "work_quest" else "New Process"
        self._build_proc = Process(name=default_name, kind=kind)
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
        try:
            proc = load_process(file_path)
        except OSError as exc:
            return
        if not proc.kind:
            proc.kind = "work_quest" if file_path.suffix == ".wrkqst" else "process"
        self._process   = proc
        self._proc_path = file_path
        self._build_dir = file_path.parent
        save_session(file_path.parent, file_path.name)
        self._show_run()

    def _is_work_quest_active(self) -> bool:
        return (
            self._mode == "run"
            and self._process is not None
            and self._process.kind == "work_quest"
        )

    def _tick_clock(self) -> None:
        if self._is_work_quest_active():
            self._refresh_quest_clock_widgets()

    def _format_minutes(self, minutes: int) -> str:
        h = max(0, minutes // 60)
        m = max(0, minutes % 60)
        # Keep Digits fixed-width for readability.
        return f"{str(h).zfill(2)}:{str(m).zfill(2)}"

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

        # Remember which top-level step indices are currently collapsed
        # so we can restore the user's expand/collapse state after the rebuild.
        collapsed: set[int] = set()
        for node in tree.root.children:
            if node.data is not None and not node.is_expanded:
                collapsed.add(node.data)

        root_label = Text(proc.name)
        if proc.completed:
            root_label.stylize("bold green")
        else:
            root_label.stylize(f"bold {_SALMON}")
        tree.reset(root_label)
        tree.root.data = None

        i = 0
        while i < len(proc.steps):
            step = proc.steps[i]
            if step.level != 1:
                i += 1
                continue

            # Find span of sub-steps
            j = i + 1
            while j < len(proc.steps) and proc.steps[j].level == 2:
                j += 1

            if j > i + 1:  # has sub-steps
                sub_steps = proc.steps[i + 1:j]
                sub_done  = sum(1 for s in sub_steps if s.completed)
                sub_total = j - i - 1
                should_expand = i not in collapsed
                node = tree.root.add(
                    _step_label(step, sub_done=sub_done, sub_total=sub_total),
                    data=i, expand=should_expand,
                )
                for k in range(i + 1, j):
                    node.add_leaf(_step_label(proc.steps[k]), data=k)
            else:
                tree.root.add_leaf(_step_label(step), data=i)

            i = j

        tree.root.expand()

    def _refresh_run_sidebar(self) -> None:
        if not self._process:
            return
        proc = self._process
        pct  = proc.progress_pct

        name_t = Text(proc.name, style=f"bold {_SALMON}")
        self.query_one("#run_name", Static).update(name_t)

        prog_t = Text()
        prog_t.append(f"{_progress_bar(pct)}\n", style=_GREEN)
        prog_t.append(f"{proc.done_top}/{proc.total_top} tasks  ", style=_KHAKI)
        prog_t.append(f"{pct:.0f}%", style=_GOLD)
        self.query_one("#run_progress", Static).update(prog_t)

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
        step = self._process.steps[node.data]
        t = Text()
        # Task label
        t.append(step.label + "\n", style=f"bold {_SALMON}")
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
                        ts = f"  {dt.strftime('%H:%M')}"
                    except ValueError:
                        pass
                t.append(f"\u2713 Done{ts}\n", style=_GREEN)
            if step.duration_minutes > 0:
                t.append(
                    f"Duration {self._format_minutes(step.duration_minutes)}\n",
                    style=_TEAL,
                )
        elif step.started:
            t.append("\u25d4 In Progress\n", style=f"bold {_BLUE}")
        else:
            t.append("\u25cb Pending\n", style="dim")
        # Note
        if step.note:
            t.append("\nNote\n", style="dim")
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
        info.update(t)
        self._refresh_focus_cursor_state()

    def _refresh_focus_cursor_state(self) -> None:
        tree = self.query_one("#process_tree", Tree)
        tree.remove_class("cursor-started")

        if self._mode != "run" or not self._process:
            return

        node = tree.cursor_node
        if node is None or node.data is None:
            return

        step = self._process.steps[node.data]
        if step.started and not step.completed:
            tree.add_class("cursor-started")

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

        if self._process.kind == "work_quest" and not self._process.clocked_in:
            return

        if step.completed:
            return

        # Work quest flow: first right starts, second right completes.
        if self._process.kind == "work_quest" and not step.started:
            step.started = True
            step.started_at = datetime.now().isoformat()
            save_process(self._process, self._proc_path)
            self._rebuild_proc_tree()
            self._refresh_run_sidebar()
            self._refresh_status()
            self._update_step_info()
            return

        # Parent node complete gate: only complete when all sub-steps are done.
        if node.children:
            subs = self._process.sub_steps_of(step_idx)
            if not subs or any(not s.completed for _, s in subs):
                return

        if step.has_threshold():
            self._pending_thresh_idx = step_idx
            self.push_screen(
                ThresholdScreen(step.label, step.threshold_upper, step.threshold_lower),
                callback=self._on_threshold_result,
            )
        else:
            self._do_complete(step_idx)

    def _on_threshold_result(self, value_str: str | None) -> None:
        if value_str is None or self._pending_thresh_idx < 0:
            return
        step_idx = self._pending_thresh_idx
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
            step.started = True
            step.started_at = now.isoformat()

        if proc.kind == "work_quest" and step.started_at:
            try:
                started = datetime.fromisoformat(step.started_at)
                step.duration_minutes = max(0, int((now - started).total_seconds() // 60))
            except ValueError:
                step.duration_minutes = 0

        step.completed    = True
        step.completed_at = now.isoformat()
        step.result       = result

        # Auto-complete parent if all siblings are done
        if step.level == 2:
            parent_idx = proc.parent_of(step_idx)
            if parent_idx is not None:
                subs = proc.sub_steps_of(parent_idx)
                if all(s.completed for _, s in subs):
                    parent = proc.steps[parent_idx]
                    parent.completed    = True
                    parent.completed_at = now.isoformat()
                    if proc.kind == "work_quest":
                        if not parent.started and parent.started_at:
                            parent.started = True
                        if parent.started_at:
                            try:
                                parent_start = datetime.fromisoformat(parent.started_at)
                                parent.duration_minutes = max(
                                    0, int((now - parent_start).total_seconds() // 60)
                                )
                            except ValueError:
                                parent.duration_minutes = 0

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
        can_revert_started = proc.kind == "work_quest" and step.started and not step.completed
        if not step.completed and not can_revert_started:
            return

        # Block uncomplete on a completed parent when all its sub-tasks are still done.
        # The user must undo a child first.
        if step.level == 1 and step.completed:
            subs = proc.sub_steps_of(step_idx)
            if subs and all(s.completed for _, s in subs):
                return

        # Revert to "not even started".
        step.started      = False
        step.started_at   = ""
        step.completed    = False
        step.completed_at = ""
        step.result       = ""
        step.duration_minutes = 0

        # Un-complete parent if it was auto-completed
        if step.level == 2:
            parent_idx = proc.parent_of(step_idx)
            if parent_idx is not None:
                parent = proc.steps[parent_idx]
                parent.started      = False
                parent.started_at   = ""
                parent.completed    = False
                parent.completed_at = ""
                parent.duration_minutes = 0

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

    def _on_note_result(self, step_idx: int, note: str | None) -> None:
        if note is None:
            return
        self._process.steps[step_idx].note = note
        save_process(self._process, self._proc_path)
        self._rebuild_proc_tree()

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

        i = 0
        while i < len(proc.steps):
            step = proc.steps[i]
            if step.level != 1:
                i += 1
                continue
            j = i + 1
            while j < len(proc.steps) and proc.steps[j].level == 2:
                j += 1
            if j > i + 1:
                node = tree.root.add(_builder_label(step), data=i, expand=True)
                for k in range(i + 1, j):
                    node.add_leaf(_builder_label(proc.steps[k]), data=k)
            else:
                tree.root.add_leaf(_builder_label(step), data=i)
            i = j

        tree.root.expand()

    def _focused_build_idx(self) -> int | None:
        node = self.query_one("#builder_tree", Tree).cursor_node
        return None if (node is None or node.data is None) else node.data

    def action_add_step(self) -> None:
        if self._mode != "build":
            return
        self.push_screen(
            StepScreen(title="Add Top-Level Task"),
            callback=self._on_add_step,
        )

    def _on_add_step(self, data: dict | None) -> None:
        if data is None or not self._build_proc:
            return
        cur_idx = self._focused_build_idx()
        if cur_idx is not None:
            insert_at = cur_idx + 1
            while (insert_at < len(self._build_proc.steps)
                   and self._build_proc.steps[insert_at].level == 2):
                insert_at += 1
        else:
            insert_at = len(self._build_proc.steps)
        self._build_proc.steps.insert(insert_at, Step(
            label=data["label"], level=1,
            note=data["note"],
            threshold_upper=data["threshold_upper"],
            threshold_lower=data["threshold_lower"],
        ))
        self._rebuild_builder_tree()
        self.query_one("#builder_tree", Tree).focus()

    def action_add_sub_step(self) -> None:
        if self._mode != "build":
            return
        self.push_screen(
            StepScreen(title="Add Sub Task"),
            callback=self._on_add_sub,
        )

    def _on_add_sub(self, data: dict | None) -> None:
        if data is None or not self._build_proc:
            return
        cur_idx = self._focused_build_idx()
        if cur_idx is None:
            return
        proc = self._build_proc
        step = proc.steps[cur_idx]
        if step.level == 2:
            insert_at = cur_idx + 1
        else:
            insert_at = cur_idx + 1
            while insert_at < len(proc.steps) and proc.steps[insert_at].level == 2:
                insert_at += 1
        proc.steps.insert(insert_at, Step(
            label=data["label"], level=2,
            note=data["note"],
            threshold_upper=data["threshold_upper"],
            threshold_lower=data["threshold_lower"],
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
        self.push_screen(
            StepScreen(existing=step, title="Edit Task"),
            callback=lambda d: self._on_edit_step(cur_idx, d),
        )

    def _on_edit_step(self, step_idx: int, data: dict | None) -> None:
        if data is None or not self._build_proc:
            return
        step = self._build_proc.steps[step_idx]
        step.label           = data["label"]
        step.note            = data["note"]
        step.threshold_upper = data["threshold_upper"]
        step.threshold_lower = data["threshold_lower"]
        self._rebuild_builder_tree()

    def action_delete_step(self) -> None:
        if self._mode != "build":
            return
        cur_idx = self._focused_build_idx()
        if cur_idx is None:
            return
        proc = self._build_proc
        step = proc.steps[cur_idx]
        if step.level == 1:
            end = cur_idx + 1
            while end < len(proc.steps) and proc.steps[end].level == 2:
                end += 1
            del proc.steps[cur_idx:end]
        else:
            del proc.steps[cur_idx]
        self._rebuild_builder_tree()
        self.query_one("#builder_tree", Tree).focus()

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
            label.update(self._build_path.name)
        else:
            label.update("New (unsaved)")

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
        except OSError:
            pass

    # ── Tree cursor events ────────────────────────────────────────────────────
    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.tree.id == "process_tree":
            self._update_step_info()

    # ── Binding guards ────────────────────────────────────────────────────────
    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action in ("complete_step", "uncomplete_step", "note_step"):
            return self._mode == "run"
        if action == "toggle_clock":
            return self._mode == "run"
        if action in ("add_step", "add_sub_step", "edit_step", "delete_step"):
            return self._mode == "build" and not isinstance(self.focused, Input)
        if action == "save_build":
            return self._mode == "build"
        return True

    # ── Global back / quit ────────────────────────────────────────────────────
    def action_go_back(self) -> None:
        self._show_home()


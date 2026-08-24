"""
VeriTrakk  -  storage.py
Clean CSV-based data model replacing the old tag-string format.
Legacy .prcss files are auto-detected and converted on load.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
_APP_ROOT    = Path(__file__).resolve().parent.parent
DATA_DIR     = _APP_ROOT / "data"
LOGS_DIR     = DATA_DIR / "logs"
SESSION_FILE = DATA_DIR / "session.json"


def _rgb255(red: int, green: int, blue: int) -> tuple[float, float, float]:
    return (red / 255.0, green / 255.0, blue / 255.0)


# PDF text color knobs. Change these three values to retune the exported PDF.
PDF_NOTE_TEXT_COLOR = _rgb255(163, 66, 20)           # burnt sienna — top-level task notes
PDF_SUBTASK_TEXT_COLOR = _rgb255(58, 90, 128)        # muted slate blue — subtask rows
PDF_SUBTASK_NOTE_TEXT_COLOR = _rgb255(21, 116, 108)  # deep teal — subtask notes


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class Step:
    label: str
    level: int                # 1 = top-level step, 2+ = nested child depth
    started: bool = False
    started_at: str = ""      # ISO-8601 string
    paused: bool = False
    active_since: str = ""    # ISO-8601 string while actively in progress
    completed: bool = False
    completed_at: str = ""    # ISO-8601 string
    duration_minutes: int = 0
    duration_seconds: int = 0
    note: str = ""
    threshold_upper: str = ""
    threshold_lower: str = ""
    manual_pass_fail: bool = False
    requires_text_input: bool = False
    captured_text_input: str = ""
    result: str = ""          # "PASS" | "FAIL" | ""
    linked_process_path: str = ""
    main_quest: bool = False

    def has_threshold(self) -> bool:
        return bool(self.threshold_upper or self.threshold_lower)


@dataclass
class Process:
    name: str
    kind: str = "process"      # "process" | "work_quest"
    spawn_instances: bool = True
    steps: list[Step] = field(default_factory=list)
    clocked_in: bool = False
    clock_active_since: str = ""
    clock_events: list[str] = field(default_factory=list)
    clock_adjust_seconds: int = 0
    completed: bool = False
    completed_at: str = ""

    @property
    def top_steps(self) -> list[tuple[int, Step]]:
        """(global_index, step) for every level-1 step."""
        return [(i, s) for i, s in enumerate(self.steps) if s.level == 1]

    @property
    def total_top(self) -> int:
        return sum(1 for s in self.steps if s.level == 1)

    @property
    def done_top(self) -> int:
        return sum(1 for s in self.steps if s.level == 1 and s.completed)

    @property
    def progress_pct(self) -> float:
        return (self.done_top / self.total_top * 100) if self.total_top else 0.0

    def is_fully_complete(self) -> bool:
        tops = [s for s in self.steps if s.level == 1]
        return bool(tops) and all(s.completed for s in tops)

    def sub_steps_of(self, top_idx: int) -> list[tuple[int, Step]]:
        """Backward-compatible alias for descendants of a top-level step."""
        return self.descendants_of(top_idx)

    def parent_of(self, sub_idx: int) -> int | None:
        """Return the global index of the nearest parent for a child step."""
        if sub_idx <= 0 or sub_idx >= len(self.steps):
            return None
        level = self.steps[sub_idx].level
        for i in range(sub_idx - 1, -1, -1):
            if self.steps[i].level < level:
                return i
        return None

    def subtree_end_exclusive(self, idx: int) -> int:
        """Index after this step and all descendants in pre-order list form."""
        if idx < 0 or idx >= len(self.steps):
            return idx
        level = self.steps[idx].level
        j = idx + 1
        while j < len(self.steps) and self.steps[j].level > level:
            j += 1
        return j

    def descendants_of(self, parent_idx: int) -> list[tuple[int, Step]]:
        """Return all descendants of a step (any depth)."""
        if parent_idx < 0 or parent_idx >= len(self.steps):
            return []
        parent_level = self.steps[parent_idx].level
        result: list[tuple[int, Step]] = []
        j = parent_idx + 1
        while j < len(self.steps) and self.steps[j].level > parent_level:
            result.append((j, self.steps[j]))
            j += 1
        return result

    def children_of(self, parent_idx: int) -> list[tuple[int, Step]]:
        """Return immediate children of a step (exactly one level deeper)."""
        if parent_idx < 0 or parent_idx >= len(self.steps):
            return []
        parent_level = self.steps[parent_idx].level
        child_level = parent_level + 1
        result: list[tuple[int, Step]] = []
        j = parent_idx + 1
        while j < len(self.steps) and self.steps[j].level > parent_level:
            step = self.steps[j]
            if step.level == child_level:
                result.append((j, step))
                j = self.subtree_end_exclusive(j)
                continue
            j += 1
        return result

    def has_children(self, idx: int) -> bool:
        if idx < 0 or idx >= len(self.steps):
            return False
        nxt = idx + 1
        return nxt < len(self.steps) and self.steps[nxt].level > self.steps[idx].level

    def last_descendant_idx(self, idx: int) -> int:
        end = self.subtree_end_exclusive(idx)
        return max(idx, end - 1)

    def total_clock_seconds(self) -> int:
        """Total clocked seconds from IN/OUT events + active clock-in window."""
        total = 0
        active_in: datetime | None = None

        for event in self.clock_events:
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
                delta = dt - active_in
                total += max(0, int(delta.total_seconds()))
                active_in = None

        if self.clocked_in and self.clock_active_since:
            try:
                active = datetime.fromisoformat(self.clock_active_since)
                delta = datetime.now() - active
                total += max(0, int(delta.total_seconds()))
            except ValueError:
                pass

        return max(0, total + self.clock_adjust_seconds)

    def total_clock_minutes(self) -> int:
        """Total clocked minutes from IN/OUT events + active clock-in window."""
        return self.total_clock_seconds() // 60


# ── CSV I/O ───────────────────────────────────────────────────────────────────

_FIELDS = [
    "kind", "spawn_instances", "clocked_in", "clock_active_since", "clock_events", "clock_adjust_seconds",
    "level", "label", "completed", "completed_at",
    "started", "started_at", "paused", "active_since", "duration_minutes", "duration_seconds",
    "note", "threshold_upper", "threshold_lower", "manual_pass_fail", "requires_text_input", "captured_text_input", "result", "linked_process_path", "main_quest",
]


def save_process(proc: Process, file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        w.writeheader()
        w.writerow({
            "kind": proc.kind,
            "spawn_instances": proc.spawn_instances,
            "clocked_in": proc.clocked_in,
            "clock_active_since": proc.clock_active_since,
            "clock_events": json.dumps(proc.clock_events),
            "clock_adjust_seconds": proc.clock_adjust_seconds,
            "level": 0, "label": proc.name,
            "completed": proc.completed, "completed_at": proc.completed_at,
            "started": "", "started_at": "", "paused": "", "active_since": "", "duration_minutes": "", "duration_seconds": "",
            "note": "", "threshold_upper": "", "threshold_lower": "", "manual_pass_fail": "", "requires_text_input": "", "captured_text_input": "", "result": "", "linked_process_path": "", "main_quest": "",
        })
        for s in proc.steps:
            w.writerow({
                "kind": "",
                "clocked_in": "",
                "clock_active_since": "",
                "clock_events": "",
                "level": s.level, "label": s.label,
                "completed": s.completed, "completed_at": s.completed_at,
                "started": s.started,
                "started_at": s.started_at,
                "paused": s.paused,
                "active_since": s.active_since,
                "duration_minutes": s.duration_minutes,
                "duration_seconds": s.duration_seconds,
                "note": s.note,
                "threshold_upper": s.threshold_upper,
                "threshold_lower": s.threshold_lower,
                "manual_pass_fail": s.manual_pass_fail,
                "requires_text_input": s.requires_text_input,
                "captured_text_input": s.captured_text_input,
                "result": s.result,
                "linked_process_path": s.linked_process_path,
                "main_quest": s.main_quest,
            })


def load_process(file_path: Path) -> Process:
    """Load a .prcss file -- tries new CSV format first, falls back to legacy."""
    try:
        return _load_csv(file_path)
    except Exception:
        return _load_legacy(file_path)


def _load_csv(file_path: Path) -> Process:
    with open(file_path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows or "level" not in rows[0]:
        raise ValueError("Not a CSV process file")
    root = rows[0]
    kind = root.get("kind", "").strip()
    if not kind:
        kind = "work_quest" if file_path.suffix == ".wrkqst" else "process"
    spawn_instances_raw = root.get("spawn_instances", "true").strip().lower()
    spawn_instances = spawn_instances_raw not in ("false", "0", "no", "off")
    events_raw = root.get("clock_events", "")
    try:
        clock_events = json.loads(events_raw) if events_raw else []
    except Exception:
        clock_events = []

    proc = Process(
        name=root["label"],
        kind=kind,
        spawn_instances=spawn_instances,
        clocked_in=root.get("clocked_in", "false").lower() == "true",
        clock_active_since=root.get("clock_active_since", ""),
        clock_events=clock_events if isinstance(clock_events, list) else [],
        clock_adjust_seconds=int(root.get("clock_adjust_seconds", "0") or "0"),
        completed=root.get("completed", "false").lower() == "true",
        completed_at=root.get("completed_at", ""),
    )
    for row in rows[1:]:
        dur_raw = row.get("duration_minutes", "0").strip()
        try:
            duration_minutes = int(dur_raw or "0")
        except ValueError:
            duration_minutes = 0
        dur_sec_raw = row.get("duration_seconds", "").strip()
        try:
            duration_seconds = int(dur_sec_raw) if dur_sec_raw else duration_minutes * 60
        except ValueError:
            duration_seconds = duration_minutes * 60
        proc.steps.append(Step(
            label=row["label"],
            level=int(row.get("level", 1)),
            started=row.get("started", "false").lower() == "true",
            started_at=row.get("started_at", ""),
            paused=row.get("paused", "false").lower() == "true",
            active_since=row.get("active_since", ""),
            completed=row.get("completed", "false").lower() == "true",
            completed_at=row.get("completed_at", ""),
            duration_minutes=duration_minutes,
            duration_seconds=duration_seconds,
            note=row.get("note", ""),
            threshold_upper=row.get("threshold_upper", ""),
            threshold_lower=row.get("threshold_lower", ""),
            manual_pass_fail=row.get("manual_pass_fail", "false").strip().lower() in ("true", "1", "yes", "on"),
            requires_text_input=row.get("requires_text_input", "false").strip().lower() in ("true", "1", "yes", "on"),
            captured_text_input=row.get("captured_text_input", ""),
            result=row.get("result", ""),
            linked_process_path=row.get("linked_process_path", ""),
            main_quest=row.get("main_quest", "false").strip().lower() in ("true", "1", "yes", "on"),
        ))
    return proc


def _load_legacy(file_path: Path) -> Process:
    """Parse the original tag-based .prcss format and convert to the new model."""
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    def _strip(s: str) -> str:
        s = re.sub(r'\|\[d=[^\]]*\]', '', s)
        s = re.sub(r'\|\[n=[^\]]*\]', '', s)
        s = re.sub(r'\[UT=[^\]]*\]', '', s)
        s = re.sub(r'\[LT=[^\]]*\]', '', s)
        s = re.sub(r'\[PASS\]|\[FAIL\]', '', s)
        return s.replace("[S]|", "").replace("[>]|", "").strip()

    def _note(s: str) -> str:
        m = re.search(r'\|\[n=([^\]]*)\]', s)
        return m.group(1) if m else ""

    def _thresh(s: str) -> tuple[str, str]:
        ut = re.search(r'\[UT=([^\]]*)\]', s)
        lt = re.search(r'\[LT=([^\]]*)\]', s)
        return (ut.group(1) if ut else ""), (lt.group(1) if lt else "")

    def _ts(s: str) -> str:
        m = re.search(r'\|\[d=([^\]]*)\]', s)
        if not m:
            return ""
        try:
            return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").isoformat()
        except ValueError:
            return m.group(1)

    if not lines:
        return Process(name="Unnamed Process")

    root_raw = lines[0].strip()
    proc = Process(
        name=_strip(root_raw),
        kind="work_quest" if file_path.suffix == ".wrkqst" else "process",
        completed="[S]|" in root_raw,
        completed_at=_ts(root_raw),
    )
    for line in lines[1:]:
        raw = line.strip()
        if not raw:
            continue
        pf = re.search(r'\[(PASS|FAIL)\]', raw)
        ut, lt = _thresh(raw)
        proc.steps.append(Step(
            label=_strip(raw),
            level=2 if "[>]|" in raw else 1,
            started=False,
            started_at="",
            paused=False,
            active_since="",
            completed="[S]|" in raw,
            completed_at=_ts(raw),
            duration_minutes=0,
            duration_seconds=0,
            note=_note(raw),
            threshold_upper=ut,
            threshold_lower=lt,
            manual_pass_fail=False,
            requires_text_input=False,
            captured_text_input="",
            result=pf.group(1) if pf else "",
            linked_process_path="",
            main_quest=False,
        ))
    return proc


# ── Session persistence ───────────────────────────────────────────────────────

def load_session() -> tuple[Path, str] | None:
    try:
        d = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return Path(d["path"]), d["file"]
    except Exception:
        return None


def save_session(directory: Path, file_name: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(
        json.dumps({"path": str(directory), "file": file_name}),
        encoding="utf-8",
    )


# ── File naming ───────────────────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
    return (safe or "new_process") + ".prcss"


def sanitize_filename_for(name: str, kind: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
    ext = ".wrkqst" if kind == "work_quest" else ".prcss"
    return (safe or "new_process") + ext


def is_base_process(file_path: Path) -> bool:
    """Return True if file_path is a base .prcss template (no '#' in stem)."""
    return file_path.suffix == ".prcss" and "#" not in file_path.stem


def create_process_instance(base_path: Path, run_id: str = "") -> Path:
    """Copy a base .prcss file to a fresh timestamped instance and return the instance path."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_id = re.sub(r'[<>:"/\\|?*\[\]#]+', "_", run_id).strip() if run_id else ""
    if safe_id:
        instance_name = f"{base_path.stem}[{safe_id}]#{ts}{base_path.suffix}"
    else:
        instance_name = f"{base_path.stem}#{ts}{base_path.suffix}"
    instance_path = base_path.parent / instance_name
    shutil.copy2(base_path, instance_path)
    return instance_path


# ── Log generation / publishing ───────────────────────────────────────────────

def _hours_text(minutes: int) -> str:
    return f"{minutes / 60:.2f} h"


def _format_log_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%Y-%m-%d %I:%M:%S %p").replace(" 0", " ", 1)


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
        .replace("\n", " ")
    )


def _pdf_stream_text(x: float, y: float, text: str, *, font: str, size: int, rgb: tuple[float, float, float]) -> str:
    r, g, b = rgb
    return (
        "BT\n"
        f"/{font} {size} Tf\n"
        f"{r:.3f} {g:.3f} {b:.3f} rg\n"
        f"1 0 0 1 {x:.2f} {y:.2f} Tm\n"
        f"({_pdf_escape(text)}) Tj\n"
        "ET"
    )


def _pdf_stream_rect(x: float, y: float, width: float, height: float, *, fill_rgb: tuple[float, float, float] | None = None, stroke_rgb: tuple[float, float, float] | None = None, line_width: float = 1.0) -> str:
    parts: list[str] = ["q"]
    if fill_rgb is not None:
        parts.append(f"{fill_rgb[0]:.3f} {fill_rgb[1]:.3f} {fill_rgb[2]:.3f} rg")
    if stroke_rgb is not None:
        parts.append(f"{stroke_rgb[0]:.3f} {stroke_rgb[1]:.3f} {stroke_rgb[2]:.3f} RG")
        parts.append(f"{line_width:.2f} w")
    parts.append(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re")
    if fill_rgb is not None and stroke_rgb is not None:
        parts.append("B")
    elif fill_rgb is not None:
        parts.append("f")
    else:
        parts.append("S")
    parts.append("Q")
    return "\n".join(parts)


# Standard Helvetica / Helvetica-Bold glyph widths (AFM units per 1000 em) for
# printable ASCII. Helvetica-Oblique shares the regular metrics. These let us
# wrap and size text against the font's real widths instead of a fixed
# characters-per-line guess, which is what let long labels/notes silently
# overflow (and clip past) their container in the old layout.
_HELV_WIDTHS: dict[str, int] = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556, "7": 556,
    "8": 556, "9": 556, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556,
    "@": 1015,
    "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722,
    "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944, "X": 667,
    "Y": 667, "Z": 611,
    "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556, "h": 556,
    "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556, "o": 556, "p": 556,
    "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500, "w": 722, "x": 500,
    "y": 500, "z": 500,
    "{": 334, "|": 260, "}": 334, "~": 584,
}

_HELV_BOLD_WIDTHS: dict[str, int] = {
    " ": 278, "!": 333, '"': 474, "#": 556, "$": 556, "%": 889, "&": 722, "'": 238,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556, "7": 556,
    "8": 556, "9": 556, ":": 333, ";": 333, "<": 584, "=": 584, ">": 584, "?": 611,
    "@": 975,
    "A": 722, "B": 722, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722,
    "I": 278, "J": 556, "K": 722, "L": 611, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944, "X": 667,
    "Y": 667, "Z": 611,
    "[": 333, "\\": 278, "]": 333, "^": 584, "_": 556, "`": 333,
    "a": 556, "b": 611, "c": 556, "d": 611, "e": 556, "f": 333, "g": 611, "h": 611,
    "i": 278, "j": 278, "k": 556, "l": 278, "m": 889, "n": 611, "o": 611, "p": 611,
    "q": 611, "r": 389, "s": 556, "t": 333, "u": 611, "v": 556, "w": 778, "x": 556,
    "y": 556, "z": 500,
    "{": 389, "|": 280, "}": 389, "~": 584,
}

_DEFAULT_GLYPH_WIDTH = 556  # fallback for characters outside the tables above


def _text_width(text: str, *, font: str, size: int) -> float:
    table = _HELV_BOLD_WIDTHS if font == "F2" else _HELV_WIDTHS
    return sum(table.get(ch, _DEFAULT_GLYPH_WIDTH) for ch in text) * size / 1000.0


def _wrap_to_width(text: str, *, font: str, size: int, width: float, first_line_width: float | None = None) -> list[str]:
    """Greedy word-wrap measured against real glyph widths, not a char count.

    `first_line_width` lets the first line be narrower than the rest (used to
    leave room for a status badge beside a wrapped title). A single token
    wider than a whole line (a long unbroken identifier, say) is hard-broken
    by character rather than left to run off the page edge.
    """
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    limit = first_line_width if first_line_width is not None else width

    def fits(s: str) -> bool:
        return _text_width(s, font=font, size=size) <= limit

    for word in words:
        candidate = f"{current} {word}".strip()
        if fits(candidate):
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
            limit = width
        if fits(word):
            current = word
            continue
        chunk = ""
        for ch in word:
            piece = chunk + ch
            if chunk and not fits(piece):
                lines.append(chunk)
                limit = width
                chunk = ch
            else:
                chunk = piece
        current = chunk
    lines.append(current)
    return lines


def _build_pdf_document(page_streams: list[str]) -> bytes:
    objects: list[bytes] = []

    def add_object(payload: str | bytes) -> int:
        data = payload.encode("latin-1") if isinstance(payload, str) else payload
        objects.append(data)
        return len(objects)

    # WinAnsiEncoding matches Latin-1 for the byte range this module writes
    # (content streams are encoded as latin-1), so non-ASCII marks like the
    # middle dot used as a separator render as the intended glyph rather than
    # whatever falls at that byte in each font's default StandardEncoding.
    font_regular = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_bold = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    font_oblique = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>")

    page_ids: list[int] = []
    content_ids: list[int] = []
    pages_id_placeholder = len(objects) + 1
    add_object(b"")

    for stream in page_streams:
        stream_bytes = stream.encode("latin-1")
        content_id = add_object(
            b"<< /Length " + str(len(stream_bytes)).encode("ascii") + b" >>\nstream\n" + stream_bytes + b"\nendstream"
        )
        content_ids.append(content_id)
        page_id = add_object(
            "<< /Type /Page /Parent {pages} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R /F3 {font_oblique} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        page_ids.append(page_id)

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id_placeholder - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1")
    )
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id_placeholder} 0 R >>")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("ascii"))
        if idx in page_ids:
            page_text = obj.decode("latin-1").replace("{pages}", str(pages_id_placeholder))
            pdf.extend(page_text.encode("latin-1"))
        else:
            pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(pdf)


def generate_log_pdf_bytes(proc: Process, published_at: datetime | None = None) -> bytes:
    """A log is only ever generated for an already-#COMPLETE process/quest, and
    completion syncs top-down (a parent can't be complete unless every one of
    its descendants is), so "COMPLETE"/"DONE" status is true of every row by
    construction — printing it everywhere just repeats the obvious. Status is
    only surfaced when it says something *other* than that (FAIL, or an
    unexpected still-open item), which is also the only case worth a visual
    flag. That's why plain-complete rows carry no badge/tag at all below.
    """
    published_dt = published_at or datetime.now()
    published_text = published_dt.strftime("%Y-%m-%d %I:%M:%S %p").replace(" 0", " ", 1)
    is_wq = proc.kind == "work_quest"
    title = "WORK QUEST LOG" if is_wq else "PROCESS LOG"
    subject = "Work Quest" if is_wq else "Process"
    total_minutes = proc.total_clock_minutes() if is_wq else sum(step.duration_minutes for step in proc.steps)

    page_width = 612.0
    page_height = 792.0
    margin = 48.0
    content_width = page_width - margin * 2
    indent_step = 13.0

    note_color = PDF_NOTE_TEXT_COLOR
    subtask_color = PDF_SUBTASK_TEXT_COLOR
    subtask_note_color = PDF_SUBTASK_NOTE_TEXT_COLOR

    color_title = (0.09, 0.11, 0.15)
    color_meta  = (0.40, 0.43, 0.47)
    color_good    = (0.13, 0.52, 0.32)
    color_bad     = (0.76, 0.20, 0.18)
    color_pending = (0.72, 0.57, 0.05)
    color_rule  = (0.85, 0.85, 0.83)

    def status_rgb(text: str) -> tuple[float, float, float]:
        if text in ("PASS", "COMPLETE", "DONE"):
            return color_good
        if text == "FAIL":
            return color_bad
        return color_pending

    pages: list[list[str]] = [[]]
    cursor_top = margin

    def new_page() -> None:
        nonlocal cursor_top
        pages.append([])
        cursor_top = margin

    def ensure_space(height: float) -> None:
        nonlocal cursor_top
        if cursor_top + height > page_height - margin:
            new_page()

    def draw_rect(top: float, height: float, *, fill_rgb: tuple[float, float, float] | None = None, x: float = margin, width: float = content_width) -> None:
        y = page_height - top - height
        pages[-1].append(_pdf_stream_rect(x, y, width, height, fill_rgb=fill_rgb))

    def draw_text(top: float, text: str, *, size: float = 11, font: str = "F1", rgb: tuple[float, float, float] = (0.12, 0.13, 0.17), x: float = margin) -> None:
        baseline = page_height - top - size
        pages[-1].append(_pdf_stream_text(x, baseline, text, font=font, size=size, rgb=rgb))

    def draw_hr(top: float) -> None:
        draw_rect(top, 0.75, fill_rgb=color_rule)

    def write_wrapped(text: str, *, x: float, width: float, size: float, font: str, rgb: tuple[float, float, float], line_h: float, first_line_width: float | None = None) -> None:
        nonlocal cursor_top
        lines = _wrap_to_width(text, font=font, size=size, width=width, first_line_width=first_line_width)
        ensure_space(len(lines) * line_h)
        for line in lines:
            draw_text(cursor_top, line, size=size, font=font, rgb=rgb, x=x)
            cursor_top += line_h

    def write_note(text: str, *, x: float, width: float, size: float, font: str, rgb: tuple[float, float, float], line_h: float, label: str) -> None:
        nonlocal cursor_top
        label_w = _text_width(label, font=font, size=size)
        for raw in text.splitlines() or [text]:
            lines = _wrap_to_width(raw, font=font, size=size, width=width - label_w)
            ensure_space(len(lines) * line_h)
            for idx, line in enumerate(lines):
                if idx == 0:
                    draw_text(cursor_top, label + line, size=size, font=font, rgb=rgb, x=x)
                else:
                    draw_text(cursor_top, line, size=size, font=font, rgb=rgb, x=x + label_w)
                cursor_top += line_h

    def write_subtask_line(text: str, *, x: float, width: float, size: float, tag: str, tag_rgb: tuple[float, float, float]) -> None:
        # Like write_note, but the leading "tag" (if any) is bold and colored
        # by status while the rest of the (hanging-indented) line stays in
        # the plain subtask color — a plain "DONE" tag is simply omitted.
        nonlocal cursor_top
        tag_w = _text_width(tag, font="F2", size=size) if tag else 0.0
        lines = _wrap_to_width(text, font="F1", size=size, width=width - tag_w)
        ensure_space(len(lines) * 13.0)
        for idx, line in enumerate(lines):
            lx = x + tag_w if tag else x
            if idx == 0 and tag:
                draw_text(cursor_top, tag, size=size, font="F2", rgb=tag_rgb, x=x)
            draw_text(cursor_top, line, size=size, font="F1", rgb=subtask_color, x=lx)
            cursor_top += 13.0

    # ---- Header banner (single compact band) --------------------------------
    ensure_space(52)
    draw_rect(cursor_top, 38, fill_rgb=(0.11, 0.30, 0.42))
    draw_text(cursor_top + 12, f"VERITRAKK  ·  {title}", size=12, font="F2", rgb=(1.0, 1.0, 1.0), x=margin + 12)
    draw_text(cursor_top + 27, f"Published {published_text}", size=8, font="F3", rgb=(0.80, 0.88, 0.93), x=margin + 12)
    cursor_top += 50

    # ---- Summary (one dense line + progress bar, no boxed card) -------------
    pct = proc.progress_pct
    summary_parts = [
        f"{subject}: {proc.name}",
        f"{proc.done_top}/{proc.total_top} tasks ({pct:.0f}%)",
        f"{_hours_text(total_minutes)} ({total_minutes} min) recorded",
    ]
    if proc.completed_at:
        summary_parts.append(f"completed {_format_log_timestamp(proc.completed_at)}")
    if proc.clock_events:
        summary_parts.append(f"{len(proc.clock_events)} clock events")
    write_wrapped("  ·  ".join(summary_parts), x=margin, width=content_width, size=10, font="F1", rgb=(0.16, 0.18, 0.21), line_h=14)

    cursor_top += 5.0
    bar_h = 6.0
    ensure_space(bar_h + 14.0)
    draw_rect(cursor_top, bar_h, fill_rgb=(0.88, 0.88, 0.86))
    if pct > 0:
        draw_rect(cursor_top, bar_h, fill_rgb=color_good, width=content_width * min(pct, 100.0) / 100.0)
    cursor_top += bar_h + 14.0
    draw_hr(cursor_top)
    cursor_top += 16.0

    # ---- Task sections (flowing text, divider rules — no per-task boxes) ---
    i = 0
    first_section = True
    while i < len(proc.steps):
        step = proc.steps[i]
        if step.level != 1:
            i += 1
            continue

        descendants = proc.descendants_of(i)

        # Reserve the divider + heading together so a page break can't strand
        # a lone rule at the bottom of one page with the heading on the next.
        ensure_space((14.0 if not first_section else 0.0) + 42.0)
        if not first_section:
            draw_hr(cursor_top)
            cursor_top += 14.0
        first_section = False

        status = step.result or ("COMPLETE" if step.completed else "PENDING")
        show_badge = status != "COMPLETE"
        badge_w = _text_width(status, font="F2", size=8) + 12.0 if show_badge else 0.0
        title_lines = _wrap_to_width(step.label, font="F2", size=13, width=content_width, first_line_width=content_width - badge_w - (10.0 if show_badge else 0.0))
        ensure_space(len(title_lines) * 16.0)
        if show_badge:
            badge_rgb = status_rgb(status)
            draw_rect(cursor_top + 1.0, 13.0, fill_rgb=badge_rgb, x=margin + content_width - badge_w, width=badge_w)
            draw_text(cursor_top + 4.0, status, size=8, font="F2", rgb=(1.0, 1.0, 1.0), x=margin + content_width - badge_w + 6.0)
        for line in title_lines:
            draw_text(cursor_top, line, size=13, font="F2", rgb=color_title, x=margin)
            cursor_top += 16.0

        meta_parts = []
        if step.completed_at:
            meta_parts.append(f"Completed {_format_log_timestamp(step.completed_at)}")
        elif step.started_at:
            meta_parts.append(f"Started {_format_log_timestamp(step.started_at)}")
        if is_wq or step.duration_minutes:
            meta_parts.append(f"{_hours_text(step.duration_minutes)} ({step.duration_minutes} min)")
        if step.threshold_upper or step.threshold_lower:
            threshold_parts: list[str] = []
            if step.threshold_upper:
                threshold_parts.append(f"upper <= {step.threshold_upper}")
            if step.threshold_lower:
                threshold_parts.append(f"lower >= {step.threshold_lower}")
            meta_parts.append(" / ".join(threshold_parts))
        if meta_parts:
            write_wrapped("  ·  ".join(meta_parts), x=margin, width=content_width, size=9.5, font="F1", rgb=color_meta, line_h=13)

        if step.note:
            cursor_top += 2.0
            write_note(step.note, x=margin, width=content_width, size=9.5, font="F3", rgb=note_color, line_h=12.5, label="note: ")

        if descendants:
            cursor_top += 5.0
            for _, sub in descendants:
                sub_indent = indent_step * max(0, sub.level - step.level - 1)
                sub_x = margin + 12.0 + sub_indent
                sub_width = content_width - 12.0 - sub_indent

                sub_status = sub.result or ("DONE" if sub.completed else "OPEN")
                rest = sub.label
                if sub.completed_at:
                    rest += f"  ·  {_format_log_timestamp(sub.completed_at)}"
                if is_wq or sub.duration_minutes:
                    rest += f"  ·  {_hours_text(sub.duration_minutes)} ({sub.duration_minutes} min)"

                cursor_top += 2.0
                tag = "" if sub_status == "DONE" else f"{sub_status}  "
                write_subtask_line(rest, x=sub_x, width=sub_width, size=9.5, tag=tag, tag_rgb=status_rgb(sub_status))

                if sub.note:
                    write_note(sub.note, x=sub_x + 10.0, width=sub_width - 10.0, size=8.5, font="F3", rgb=subtask_note_color, line_h=11, label="")

        cursor_top += 12.0
        i = proc.subtree_end_exclusive(i)

    ensure_space(30.0)
    draw_hr(cursor_top)
    cursor_top += 14.0
    draw_text(cursor_top, f"Completion summary: {proc.done_top}/{proc.total_top} top-level tasks complete", size=10, font="F2", rgb=(0.16, 0.20, 0.24), x=margin)

    total_pages = len(pages)
    for idx, page in enumerate(pages, start=1):
        page.append(_pdf_stream_text(margin, 26.0, f"VeriTrakk  ·  Page {idx} of {total_pages}", font="F1", size=8, rgb=(0.55, 0.55, 0.55)))

    return _build_pdf_document(["\n".join(page) for page in pages if page])


def generate_log_text(proc: Process, published_at: datetime | None = None) -> str:
    W = 64
    now = (published_at or datetime.now()).strftime("%Y-%m-%d %I:%M:%S %p").replace(" 0", " ", 1)
    is_wq = proc.kind == "work_quest"

    title = "  VERITRAKK  -  WORK QUEST LOG" if is_wq else "  VERITRAKK  -  PROCESS LOG"
    lines: list[str] = [
        "=" * W,
        title,
        "=" * W,
        f"  {'WorkQuest' if is_wq else 'Process'}  : {proc.name}",
        f"  Published: {now}",
    ]
    if proc.completed_at:
        try:
            dt = datetime.fromisoformat(proc.completed_at)
            lines.append(
                f"  Completed: {dt.strftime('%Y-%m-%d %I:%M:%S %p').replace(' 0', ' ', 1)}"
            )
        except ValueError:
            lines.append(f"  Completed: {proc.completed_at}")
    lines += ["=" * W, ""]

    i = 0
    while i < len(proc.steps):
        step = proc.steps[i]
        if step.level != 1:
            i += 1
            continue

        if step.result:
            status = f"[{step.result}]  COMPLETE"
        elif step.completed:
            status = "COMPLETE"
        else:
            status = "PENDING"

        ts_str = ""
        if step.completed_at:
            try:
                dt = datetime.fromisoformat(step.completed_at)
                ts_str = f"  {dt.strftime('%Y-%m-%d %I:%M:%S %p').replace(' 0', ' ', 1)}"
            except ValueError:
                ts_str = f"  {step.completed_at}"

        lines.append(f"  *  {step.label}")
        lines.append(f"     Status : {status}{ts_str}")
        if is_wq:
            lines.append(
                f"     Hours  : {_hours_text(step.duration_minutes)}"
                f"  ({step.duration_minutes} min)"
            )
        if step.note:
            lines.append(f"     Note   : {step.note}")
        if step.threshold_upper or step.threshold_lower:
            parts = []
            if step.threshold_upper:
                parts.append(f"UT={step.threshold_upper}")
            if step.threshold_lower:
                parts.append(f"LT={step.threshold_lower}")
            lines.append(f"     Thresh : {', '.join(parts)}")

        for _, sub in proc.descendants_of(i):
            if sub.result:
                sym = f"[{sub.result}]"
            elif sub.completed:
                sym = "[DONE]"
            else:
                sym = "[    ]"
            sub_ts = ""
            if sub.completed_at:
                try:
                    dt = datetime.fromisoformat(sub.completed_at)
                    sub_ts = f"  {dt.strftime('%I:%M:%S %p').lstrip('0')}"
                except ValueError:
                    sub_ts = f"  {sub.completed_at}"
            indent = "  " * max(0, sub.level - step.level - 1)
            sub_line = f"        {indent}{sym}  {sub.label}{sub_ts}"
            if is_wq:
                sub_line += (
                    f"  |  Hours {_hours_text(sub.duration_minutes)}"
                    f" ({sub.duration_minutes} min)"
                )
            lines.append(sub_line)
            if sub.note:
                lines.append(f"               NOTE: {sub.note}")

        i = proc.subtree_end_exclusive(i)
        lines.append("")

    lines += [
        "-" * W,
        f"  {proc.done_top} / {proc.total_top} top-level tasks completed",
    ]
    if is_wq:
        total_minutes = proc.total_clock_minutes()
        lines.append(
            f"  Total clocked hours: {_hours_text(total_minutes)} ({total_minutes} min)"
        )
    lines.append("=" * W)
    return "\n".join(lines)


def publish_process(proc: Process, src_path: Path) -> Path:
    """Write text and PDF logs, copy them to data/logs/, delete source. Returns the text log path."""
    published_at = datetime.now()
    log_text = generate_log_text(proc, published_at)
    pdf_bytes = generate_log_pdf_bytes(proc, published_at)
    stem     = src_path.stem.replace("#COMPLETE", "").strip()
    log_name = stem + (".wrkqstlog" if src_path.suffix == ".wrkqst" else ".prcsslog")
    pdf_name = log_name + ".pdf"
    log_path = src_path.parent / log_name
    pdf_path = src_path.parent / pdf_name

    log_path.write_text(log_text, encoding="utf-8")
    pdf_path.write_bytes(pdf_bytes)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    (LOGS_DIR / log_name).write_text(log_text, encoding="utf-8")
    (LOGS_DIR / pdf_name).write_bytes(pdf_bytes)

    if src_path.exists():
        src_path.unlink()

    return log_path

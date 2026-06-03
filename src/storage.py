"""
VeriTrakk  -  storage.py
Clean CSV-based data model replacing the old tag-string format.
Legacy .prcss files are auto-detected and converted on load.
"""
from __future__ import annotations

import csv
import json
import re
import textwrap
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
PDF_NOTE_TEXT_COLOR = _rgb255(200, 70, 0)
PDF_SUBTASK_TEXT_COLOR = _rgb255(0, 90, 210)
PDF_SUBTASK_NOTE_TEXT_COLOR = _rgb255(160, 40, 190)


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
    result: str = ""          # "PASS" | "FAIL" | ""

    def has_threshold(self) -> bool:
        return bool(self.threshold_upper or self.threshold_lower)


@dataclass
class Process:
    name: str
    kind: str = "process"      # "process" | "work_quest"
    steps: list[Step] = field(default_factory=list)
    clocked_in: bool = False
    clock_active_since: str = ""
    clock_events: list[str] = field(default_factory=list)
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

    def total_clock_minutes(self) -> int:
        """Total clocked minutes from IN/OUT events + active clock-in window."""
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
                total += max(0, int(delta.total_seconds() // 60))
                active_in = None

        if self.clocked_in and self.clock_active_since:
            try:
                active = datetime.fromisoformat(self.clock_active_since)
                delta = datetime.now() - active
                total += max(0, int(delta.total_seconds() // 60))
            except ValueError:
                pass

        return total


# ── CSV I/O ───────────────────────────────────────────────────────────────────

_FIELDS = [
    "kind", "clocked_in", "clock_active_since", "clock_events",
    "level", "label", "completed", "completed_at",
    "started", "started_at", "paused", "active_since", "duration_minutes", "duration_seconds",
    "note", "threshold_upper", "threshold_lower", "result",
]


def save_process(proc: Process, file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        w.writeheader()
        w.writerow({
            "kind": proc.kind,
            "clocked_in": proc.clocked_in,
            "clock_active_since": proc.clock_active_since,
            "clock_events": json.dumps(proc.clock_events),
            "level": 0, "label": proc.name,
            "completed": proc.completed, "completed_at": proc.completed_at,
            "started": "", "started_at": "", "paused": "", "active_since": "", "duration_minutes": "", "duration_seconds": "",
            "note": "", "threshold_upper": "", "threshold_lower": "", "result": "",
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
                "result": s.result,
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
    events_raw = root.get("clock_events", "")
    try:
        clock_events = json.loads(events_raw) if events_raw else []
    except Exception:
        clock_events = []

    proc = Process(
        name=root["label"],
        kind=kind,
        clocked_in=root.get("clocked_in", "false").lower() == "true",
        clock_active_since=root.get("clock_active_since", ""),
        clock_events=clock_events if isinstance(clock_events, list) else [],
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
            result=row.get("result", ""),
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
            result=pf.group(1) if pf else "",
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


def _build_pdf_document(page_streams: list[str]) -> bytes:
    objects: list[bytes] = []

    def add_object(payload: str | bytes) -> int:
        data = payload.encode("latin-1") if isinstance(payload, str) else payload
        objects.append(data)
        return len(objects)

    font_regular = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    font_oblique = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>")

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
    note_color = PDF_NOTE_TEXT_COLOR
    subtask_color = PDF_SUBTASK_TEXT_COLOR
    subtask_note_color = PDF_SUBTASK_NOTE_TEXT_COLOR
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

    def draw_rect(top: float, height: float, *, fill_rgb: tuple[float, float, float] | None = None, stroke_rgb: tuple[float, float, float] | None = None, x: float = margin, width: float = content_width, line_width: float = 1.0) -> None:
        y = page_height - top - height
        pages[-1].append(
            _pdf_stream_rect(x, y, width, height, fill_rgb=fill_rgb, stroke_rgb=stroke_rgb, line_width=line_width)
        )

    def draw_text(top: float, text: str, *, size: int = 11, font: str = "F1", rgb: tuple[float, float, float] = (0.12, 0.13, 0.17), x: float = margin) -> None:
        baseline = page_height - top - size
        pages[-1].append(_pdf_stream_text(x, baseline, text, font=font, size=size, rgb=rgb))

    def write_lines(lines: list[str], *, size: int = 11, font: str = "F1", rgb: tuple[float, float, float] = (0.12, 0.13, 0.17), x: float = margin, line_gap: float = 4.0) -> None:
        nonlocal cursor_top
        step = size + line_gap
        ensure_space(len(lines) * step)
        for line in lines:
            draw_text(cursor_top, line, size=size, font=font, rgb=rgb, x=x)
            cursor_top += step

    def write_wrapped(text: str, *, prefix: str = "", size: int = 11, font: str = "F1", rgb: tuple[float, float, float] = (0.12, 0.13, 0.17), x: float = margin, width_chars: int = 78, line_gap: float = 4.0) -> None:
        lines: list[str] = []
        source_lines = text.splitlines() or [""]
        for raw in source_lines:
            wrapped = textwrap.wrap(raw, width=width_chars, subsequent_indent=" " * len(prefix)) or [""]
            if prefix:
                wrapped[0] = prefix + wrapped[0]
                prefix = " " * len(prefix)
            lines.extend(wrapped)
        write_lines(lines, size=size, font=font, rgb=rgb, x=x, line_gap=line_gap)

    ensure_space(96)
    draw_rect(cursor_top, 72, fill_rgb=(0.13, 0.34, 0.46))
    draw_text(cursor_top + 14, "VERITRAKK", size=13, font="F2", rgb=(0.86, 0.92, 0.95), x=margin + 18)
    draw_text(cursor_top + 34, title, size=24, font="F2", rgb=(1.0, 1.0, 1.0), x=margin + 18)
    draw_text(cursor_top + 58, f"Published {published_text}", size=10, font="F3", rgb=(0.86, 0.92, 0.95), x=margin + 18)
    cursor_top += 88

    meta_height = 112 if proc.completed_at else 94
    ensure_space(meta_height + 12)
    draw_rect(cursor_top, meta_height, fill_rgb=(0.96, 0.96, 0.95), stroke_rgb=(0.84, 0.84, 0.82))
    meta_lines = [
        f"{subject}: {proc.name}",
        f"Top-level tasks completed: {proc.done_top} / {proc.total_top}",
        f"Recorded time: {_hours_text(total_minutes)} ({total_minutes} min)",
    ]
    if proc.completed_at:
        meta_lines.append(f"Completed: {_format_log_timestamp(proc.completed_at)}")
    if proc.clock_events:
        meta_lines.append(f"Clock events captured: {len(proc.clock_events)}")
    draw_text(cursor_top + 14, "Summary", size=13, font="F2", rgb=(0.16, 0.20, 0.24), x=margin + 16)
    y_meta = cursor_top + 38
    for line in meta_lines:
        draw_text(y_meta, line, size=11, font="F1", rgb=(0.18, 0.20, 0.23), x=margin + 16)
        y_meta += 18
    cursor_top += meta_height + 18

    i = 0
    while i < len(proc.steps):
        step = proc.steps[i]
        if step.level != 1:
            i += 1
            continue

        descendants = proc.descendants_of(i)

        block_lines = 4
        if is_wq:
            block_lines += 1
        if step.threshold_upper or step.threshold_lower:
            block_lines += 1
        if step.note:
            note_lines = sum(
                max(1, len(textwrap.wrap(line, width=68)))
                for line in step.note.splitlines() or [step.note]
            )
            block_lines += note_lines
        for _, sub in descendants:
            block_lines += 1
            if sub.note:
                block_lines += sum(
                    max(1, len(textwrap.wrap(line, width=62)))
                    for line in sub.note.splitlines() or [sub.note]
                )
        block_height = 26 + block_lines * 16
        ensure_space(block_height + 12)
        draw_rect(cursor_top, block_height, fill_rgb=(0.995, 0.995, 0.99), stroke_rgb=(0.87, 0.87, 0.84))

        status = step.result or ("COMPLETE" if step.completed else "PENDING")
        status_color = (0.18, 0.53, 0.34) if status in ("PASS", "COMPLETE") else (0.74, 0.20, 0.18) if status == "FAIL" else (0.66, 0.50, 0.12)
        draw_text(cursor_top + 14, step.label, size=14, font="F2", rgb=(0.12, 0.15, 0.17), x=margin + 16)
        draw_text(cursor_top + 15, status, size=10, font="F2", rgb=status_color, x=margin + content_width - 92)

        block_top = cursor_top + 38
        details = [f"Status: {status}"]
        if step.completed_at:
            details.append(f"Completed: {_format_log_timestamp(step.completed_at)}")
        elif step.started_at:
            details.append(f"Started: {_format_log_timestamp(step.started_at)}")
        if is_wq or step.duration_minutes:
            details.append(f"Step time: {_hours_text(step.duration_minutes)} ({step.duration_minutes} min)")
        if step.threshold_upper or step.threshold_lower:
            threshold_parts: list[str] = []
            if step.threshold_upper:
                threshold_parts.append(f"Upper <= {step.threshold_upper}")
            if step.threshold_lower:
                threshold_parts.append(f"Lower >= {step.threshold_lower}")
            details.append("Thresholds: " + " | ".join(threshold_parts))
        for line in details:
            draw_text(block_top, line, size=11, font="F1", rgb=(0.22, 0.24, 0.27), x=margin + 16)
            block_top += 16

        if step.note:
            cursor_snapshot = cursor_top
            cursor_top = block_top
            write_wrapped(step.note, prefix="Note: ", size=10, font="F2", rgb=note_color, x=margin + 16, width_chars=70, line_gap=3)
            block_top = cursor_top
            cursor_top = cursor_snapshot

        if descendants:
            draw_text(block_top + 2, "Subtasks", size=11, font="F2", rgb=subtask_color, x=margin + 16)
            block_top += 18
            cursor_snapshot = cursor_top
            cursor_top = block_top
            for _, sub in descendants:
                sub_status = sub.result or ("DONE" if sub.completed else "OPEN")
                indent = "  " * max(0, sub.level - step.level - 1)
                sub_line = f"{indent}- [{sub_status}] {sub.label}"
                if sub.completed_at:
                    sub_line += f"  |  {_format_log_timestamp(sub.completed_at)}"
                if is_wq or sub.duration_minutes:
                    sub_line += f"  |  {_hours_text(sub.duration_minutes)} ({sub.duration_minutes} min)"
                write_wrapped(sub_line, size=10, font="F2", rgb=subtask_color, x=margin + 28, width_chars=66, line_gap=3)
                if sub.note:
                    write_wrapped(sub.note, prefix="  note: ", size=9, font="F2", rgb=subtask_note_color, x=margin + 40, width_chars=60, line_gap=3)
            block_top = cursor_top
            cursor_top = cursor_snapshot

        cursor_top += block_height + 12
        i = proc.subtree_end_exclusive(i)

    ensure_space(44)
    draw_rect(cursor_top, 32, fill_rgb=(0.95, 0.96, 0.97))
    footer = f"Completion summary: {proc.done_top}/{proc.total_top} top-level tasks complete"
    draw_text(cursor_top + 10, footer, size=10, font="F2", rgb=(0.16, 0.20, 0.24), x=margin + 14)

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

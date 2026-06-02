"""
VeriTrakk  -  storage.py
Clean CSV-based data model replacing the old tag-string format.
Legacy .prcss files are auto-detected and converted on load.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
_APP_ROOT    = Path(__file__).resolve().parent.parent
DATA_DIR     = _APP_ROOT / "data"
LOGS_DIR     = DATA_DIR / "logs"
SESSION_FILE = DATA_DIR / "session.json"


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class Step:
    label: str
    level: int                # 1 = top-level step, 2 = sub-step
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
        """Return (global_index, step) for sub-steps belonging to top_idx."""
        result: list[tuple[int, Step]] = []
        for i in range(top_idx + 1, len(self.steps)):
            if self.steps[i].level == 1:
                break
            result.append((i, self.steps[i]))
        return result

    def parent_of(self, sub_idx: int) -> int | None:
        """Return the global index of the parent top-level step for a sub-step."""
        for i in range(sub_idx - 1, -1, -1):
            if self.steps[i].level == 1:
                return i
        return None

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

def generate_log_text(proc: Process) -> str:
    W = 64
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_wq = proc.kind == "work_quest"

    def _hours_text(minutes: int) -> str:
        return f"{minutes / 60:.2f} h"

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
            lines.append(f"  Completed: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
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
                ts_str = f"  {dt.strftime('%Y-%m-%d %H:%M:%S')}"
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

        j = i + 1
        while j < len(proc.steps) and proc.steps[j].level == 2:
            sub = proc.steps[j]
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
                    sub_ts = f"  {dt.strftime('%H:%M:%S')}"
                except ValueError:
                    sub_ts = f"  {sub.completed_at}"
            sub_line = f"        {sym}  {sub.label}{sub_ts}"
            if is_wq:
                sub_line += (
                    f"  |  Hours {_hours_text(sub.duration_minutes)}"
                    f" ({sub.duration_minutes} min)"
                )
            lines.append(sub_line)
            if sub.note:
                lines.append(f"               NOTE: {sub.note}")
            j += 1

        i = j
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
    """Write a log file, copy to data/logs/, delete source. Returns the log path."""
    log_text = generate_log_text(proc)
    stem     = src_path.stem.replace("#COMPLETE", "").strip()
    log_name = stem + (".wrkqstlog" if src_path.suffix == ".wrkqst" else ".prcsslog")
    log_path = src_path.parent / log_name

    log_path.write_text(log_text, encoding="utf-8")

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    (LOGS_DIR / log_name).write_text(log_text, encoding="utf-8")

    if src_path.exists():
        src_path.unlink()

    return log_path

"""Work quest logs (Mike, 2026-11-16): the subtask hierarchy sized and colored in
the PDF, and linked processes published with their quest and embedded in its log."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src import storage
from src.storage import (
    Process,
    Step,
    generate_log_pdf_bytes,
    generate_log_text,
    linked_logs_for,
    publish_process,
    save_process,
)


def _rg(rgb: tuple[float, float, float], op: str = "rg") -> bytes:
    return f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} {op}".encode("latin-1")


@pytest.fixture
def logs_dir(tmp_path, monkeypatch):
    out = tmp_path / "logs"
    monkeypatch.setattr(storage, "LOGS_DIR", out)
    return out


def _done(label: str, level: int, **kw) -> Step:
    return Step(label, level, started=True, completed=True, completed_at="2026-11-16T10:00:00", **kw)


def _linked_run(folder: Path, name: str = "Board Check", complete: bool = True) -> Path:
    """A run (instance) of a process, saved as it is once completed (#COMPLETE in its name)."""
    proc = Process(name, kind="process", completed=complete,
                   steps=[_done("Inspect solder joints", 1, duration_minutes=12),
                          _done("Measure rail", 2, captured_text_input="3.31 V")] if complete
                   else [Step("Inspect solder joints", 1), Step("Measure rail", 2)])
    stem = f"{name}[A1]#2026-11-16_09-00-00" + ("#COMPLETE" if complete else "")
    path = folder / f"{stem}.prcss"
    save_process(proc, path)
    return path


def _quest(link: str) -> Process:
    return Process("Week 46", kind="work_quest", completed=True, steps=[
        _done("Build boards", 1, duration_minutes=60),
        _done("Bring-up", 2, linked_process_path=link),
        _done("Rework", 2),
        _done("Rails", 3),
        _done("3V3", 4),
        _done("Note it", 3),
    ])


# ── Subtask hierarchy in the PDF ──────────────────────────────────────────────

def _styles(pdf: bytes) -> dict[str, tuple[str, float, str]]:
    """label -> (font, size, color) of each row's first piece of text."""
    rows = re.findall(r"/(F\d) ([\d.]+) Tf\n([\d.]+ [\d.]+ [\d.]+) rg\n1 0 0 1 [\d.]+ [\d.]+ Tm\n\(([^)]*?) \xb7 ",
                      pdf.decode("latin-1"))
    return {label: (font, float(size), color) for font, size, color, label in rows}


class TestSubtaskStyle:
    # Mike, 2026-11-16: a parent is bold and bigger, the next color down the line
    # (tasks black, then blue, salmon, blue...); a child with no children is in
    # its parent's color, plain and smaller, so you can see who belongs with who.
    BLUE = _rg(storage.PDF_SUBTASK_PARENT_COLORS[0])[:-3].decode()
    RED = _rg(storage.PDF_SUBTASK_PARENT_COLORS[1])[:-3].decode()
    BLACK = "0.090 0.110 0.150"   # (the task titles' color)

    def test_parents_bold_bigger_next_color_children_in_their_parents_color(self):
        s = _styles(generate_log_pdf_bytes(_quest("")))
        assert s["Rework"] == ("F2", 11.5, self.BLUE)         # first-level parent
        assert s["Rails"] == ("F2", 10.9, self.RED)        # its child, a parent too: the next color, smaller
        assert s["3V3"] == ("F1", 9.5, self.RED)           # Rails' child: salmon, plain, smaller
        assert s["Note it"] == ("F1", 9.5, self.BLUE)         # Rework's child: blue, plain, smaller
        assert s["Bring-up"] == ("F1", 9.5, self.BLACK)       # the task's own child: black, plain

    def test_it_cascades_all_the_way_down(self):
        steps = [_done("T", 1)] + [_done(f"L{n}", n) for n in range(2, 9)]
        s = _styles(generate_log_pdf_bytes(Process("Deep", kind="work_quest", completed=True, steps=steps)))
        chain = [s[f"L{n}"] for n in range(2, 9)]   # each the parent of the next; L8 has no children
        parents, leaf = chain[:-1], chain[-1]
        assert all(font == "F2" for font, _, _ in parents)
        assert [c for _, _, c in parents] == [self.BLUE, self.RED] * 3
        assert all(a[1] >= b[1] for a, b in zip(parents, parents[1:]))     # never bigger than its parent
        assert parents[0][1] > parents[1][1] > parents[2][1] > parents[3][1]
        assert all(size > leaf[1] for _, size, _ in parents)
        assert leaf == ("F1", storage.PDF_SUBTASK_LEAF_SIZE, parents[-1][2])   # in its parent's color


# ── Linked processes ──────────────────────────────────────────────────────────

class TestLinkedLogs:
    def test_completed_run_is_found_by_its_complete_name(self, tmp_path):
        run = _linked_run(tmp_path)
        stored = str(run).replace("#COMPLETE", "")   # (as linked before it was completed)
        linked = linked_logs_for(_quest(stored))
        assert list(linked) == [1] and linked[1].loggable and linked[1].path == run

    def test_publish_logs_the_linked_run_too(self, tmp_path, logs_dir):
        run = _linked_run(tmp_path)
        quest = _quest(str(run))
        quest_path = tmp_path / "Week 46#COMPLETE.wrkqst"
        save_process(quest, quest_path)

        log_path = publish_process(quest, quest_path)

        # The linked run: its file gone, and no log file of its own (Mike: the
        # quest's PDF is the one log); the quest's own source gone too. Nothing
        # but that PDF is written, here or in data/logs.
        assert not run.exists() and not quest_path.exists()
        assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["Week 46.wrkqstlog.pdf"]
        assert sorted(p.name for p in logs_dir.iterdir()) == ["Week 46.wrkqstlog.pdf"]
        assert log_path == tmp_path / "Week 46.wrkqstlog.pdf"

        # The quest's PDF embeds it under the step that links it, in plum, inside an outlined, tinted box.
        pdf = log_path.read_bytes()
        assert b"LINKED PROCESS LOG" in pdf and b"Measure rail" in pdf
        assert pdf.index(b"(Bring-up") < pdf.index(b"LINKED PROCESS LOG") < pdf.index(b"(Rework")
        assert _rg(storage.PDF_LINKED_TEXT_COLOR) in pdf
        assert _rg(storage.PDF_LINKED_TEXT_COLOR, "RG") in pdf and _rg(storage.PDF_LINKED_BOX_FILL) in pdf

    def test_template_is_kept_and_noted(self, tmp_path, logs_dir):
        template = tmp_path / "Board Check.prcss"
        save_process(Process("Board Check", kind="process", spawn_instances=True, steps=[Step("Inspect", 1)]), template)
        quest = _quest(str(template))
        quest_path = tmp_path / "Week 46#COMPLETE.wrkqst"
        save_process(quest, quest_path)

        log_path = publish_process(quest, quest_path)

        assert template.exists()
        assert not list(tmp_path.glob("Board Check*log*"))
        assert b"Board Check.prcss: a template, not run yet, not logged" in log_path.read_bytes()

    def test_unfinished_run_is_kept_and_noted(self, tmp_path, logs_dir):
        run = _linked_run(tmp_path, complete=False)
        quest_path = tmp_path / "Week 46#COMPLETE.wrkqst"
        quest = _quest(str(run))
        save_process(quest, quest_path)

        log_path = publish_process(quest, quest_path)

        assert run.exists()
        assert b"not complete, not logged" in log_path.read_bytes()

    def test_completed_one_off_process_is_logged(self, tmp_path, logs_dir):
        # A one-off process (not a template) runs in place; completed, it's "<name>#COMPLETE".
        one_off = tmp_path / "UL Documentation#COMPLETE.prcss"
        save_process(Process("UL Documentation", kind="process", spawn_instances=False, completed=True,
                             steps=[_done("Get UL info on Relays", 1)]), one_off)
        quest_path = tmp_path / "Week 46#COMPLETE.wrkqst"
        quest = _quest(str(tmp_path / "UL Documentation.prcss"))   # (linked before it was completed)
        save_process(quest, quest_path)
        log_path = publish_process(quest, quest_path)
        assert not one_off.exists() and not (tmp_path / "UL Documentation.prcsslog").exists()
        assert b"LINKED PROCESS LOG" in log_path.read_bytes() and b"UL Documentation" in log_path.read_bytes()

    def test_missing_link_is_noted(self, tmp_path, logs_dir):
        quest_path = tmp_path / "Week 46#COMPLETE.wrkqst"
        quest = _quest(str(tmp_path / "Gone#2026.prcss"))
        save_process(quest, quest_path)
        log_path = publish_process(quest, quest_path)
        assert b"file not found, not logged" in log_path.read_bytes()

    def test_long_linked_log_box_breaks_across_pages(self, tmp_path):
        run = tmp_path / "Long#2026-11-16_09-00-00#COMPLETE.prcss"
        save_process(Process("Long", kind="process", completed=True,
                             steps=[_done(f"Step {n}", 1) for n in range(120)]), run)
        pdf = generate_log_pdf_bytes(_quest(str(run)), linked=linked_logs_for(_quest(str(run))))
        assert pdf.count(_rg(storage.PDF_LINKED_TEXT_COLOR, "RG")) >= 2   # (a box segment on each page)

    def test_a_plain_process_log_is_unchanged_by_links(self):
        proc = Process("P", kind="process", completed=True, steps=[_done("A", 1, linked_process_path="x.prcss")])
        assert linked_logs_for(proc) == {}
        assert "LINKED PROCESS LOG" not in generate_log_text(proc)


class TestPdfCharacters:
    def test_curly_quotes_and_other_characters_dont_stop_the_log(self):
        # (Mike, 2026-11-16: "Update U5 section with Joel’s changes" stopped a quest being logged.)
        proc = Process("P", kind="process", completed=True,
                       steps=[_done("Update U5 section with Joel’s changes — “final” …", 1, note="Δ 5 V ✓")])
        pdf = generate_log_pdf_bytes(proc)
        assert b"Joel\x92s changes \x97 \x93final\x94 \x85" in pdf   # (WinAnsi's own curly quotes, dash, ellipsis)
        assert b"? 5 V ?" in pdf   # (no glyph for these in the PDF's fonts)


class TestGroupedOrder:
    # Mike, 2026-11-16: each parent's own plain children together right under it,
    # then each child group whole, however the quest had them mixed.
    def _quest(self) -> Process:
        return Process("Q", kind="work_quest", completed=True, steps=[
            _done("Task", 1),
            _done("Plain A", 2),
            _done("Group B", 2), _done("B leaf 1", 3), _done("Sub C", 3), _done("C leaf", 4), _done("B leaf 2", 3),
            _done("Plain D", 2),
            _done("Group E", 2), _done("E leaf", 3),
            _done("Plain F", 2),
        ])

    def test_plain_children_first_then_each_group_whole(self):
        order = [s.label for _, s in storage.grouped_descendants(self._quest(), 0)]
        assert order == ["Plain A", "Plain D", "Plain F",
                         "Group B", "B leaf 1", "B leaf 2", "Sub C", "C leaf",
                         "Group E", "E leaf"]

    def test_logs_use_that_order_for_work_quests_only(self):
        text = generate_log_text(self._quest())
        assert text.index("Plain F") < text.index("Group B") < text.index("B leaf 2") < text.index("Sub C")
        pdf = generate_log_pdf_bytes(self._quest())
        assert pdf.index(b"(Plain F") < pdf.index(b"(Group B") < pdf.index(b"(B leaf 2") < pdf.index(b"(Sub C")
        proc = self._quest()
        proc.kind = "process"   # (a process keeps its checklist order)
        text = generate_log_text(proc)
        assert text.index("Plain A") < text.index("Group B") < text.index("Plain D")


class TestCarriedOver:
    # Mike, 2026-11-16: a task Carry Over handed to the next quest is labelled
    # CARRIED OVER in its own color, not shown as done.
    def _quest(self) -> Process:
        return Process("Q", kind="work_quest", completed=True, steps=[
            _done("Task", 1),
            _done("Finished", 2, duration_minutes=30),
            _done("Handed on", 2, carried_over=True, duration_minutes=10),
            _done("Untouched", 1, carried_over=True),
        ])

    def test_round_trips_in_the_file(self, tmp_path):
        save_process(self._quest(), tmp_path / "q.wrkqst")
        back = storage.load_process(tmp_path / "q.wrkqst")
        assert [s.carried_over for s in back.steps] == [False, False, True, True]

    def test_older_files_without_the_column_load_as_not_carried(self, tmp_path):
        path = tmp_path / "old.wrkqst"
        save_process(self._quest(), path)
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(",".join(l.split(",")[:-1]) for l in lines) + "\n", encoding="utf-8")
        assert not any(s.carried_over for s in storage.load_process(path).steps)

    def test_text_log_labels_them(self):
        text = generate_log_text(self._quest())
        assert "[CARRIED OVER]  Handed on" in text and "[DONE]  Finished" in text
        assert "Status : CARRIED OVER" in text

    def test_pdf_labels_them_in_their_own_color(self):
        pdf = generate_log_pdf_bytes(self._quest())
        gray = _rg(storage.PDF_CARRIED_TEXT_COLOR)
        assert b"(CARRIED OVER  ) Tj" in pdf and gray in pdf   # the subtask's tag
        assert b"(CARRIED OVER) Tj" in pdf                     # the task's badge
        s = _styles(pdf)
        assert s["Handed on"][2] == gray[:-3].decode() and s["Finished"][2] != gray[:-3].decode()


class TestWatermark:
    # Mike, 2026-11-16: the logo, big, behind every page of a log PDF.
    def _proc(self, n: int) -> Process:
        return Process("Q", kind="work_quest", completed=True, steps=[_done(f"Step {k}", 1) for k in range(n)])

    def test_on_every_page_under_everything(self):
        pdf = generate_log_pdf_bytes(self._proc(60)).decode("latin-1")
        streams = re.findall(r"stream\n(.*?)\nendstream", pdf, re.S)
        assert len(streams) >= 2
        for stream in streams:
            assert stream.startswith("q\n")              # (drawn first: under the page's text)
            assert " cm\n0.900 0.968 0.994 rg\n" in stream  # the logo's cyan, faded 90% to white
            assert stream.count("\nf\n") >= 6             # its six shapes

    def test_svg_path_commands(self):
        ops = storage._svg_path_to_pdf("M1,2h3v4l-1-1c1,0,2,0,2,1s1,1,1,0Z").splitlines()
        assert ops[0] == "1.000 2.000 m"
        assert ops[1] == "4.000 2.000 l" and ops[2] == "4.000 6.000 l" and ops[3] == "3.000 5.000 l"
        assert ops[4] == "4.000 5.000 5.000 5.000 5.000 6.000 c"
        assert ops[5] == "5.000 7.000 6.000 7.000 6.000 6.000 c"   # (S: the first control point mirrored)
        assert ops[6] == "h"

    def test_no_logo_file_no_watermark(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage, "LOGO_SVG", tmp_path / "missing.svg")
        pdf = generate_log_pdf_bytes(self._proc(3)).decode("latin-1")
        assert re.search(r"stream\nq 1\.\d+ 0 0", pdf)   # (straight to the page's own drawing)
        assert "0.900 0.968 0.994 rg" not in pdf



class TestFilesKept:
    # Mike, 2026-11-16: logging deletes nothing; the quest and the processes logged
    # with it go in a folder beside the PDF, so they can be opened again.
    def test_quest_and_logged_processes_moved_into_the_folder(self, tmp_path, logs_dir):
        run = _linked_run(tmp_path)
        template = tmp_path / "Board Check.prcss"
        save_process(Process("Board Check", kind="process", spawn_instances=True, steps=[Step("Inspect", 1)]), template)
        quest = _quest(str(run))
        quest.steps[2].linked_process_path = str(template)   # ("Rework" links the template: never run)
        quest_path = tmp_path / "Week 46#COMPLETE.wrkqst"
        save_process(quest, quest_path)

        plan = storage.log_plan(quest, quest_path)
        assert plan.folder == tmp_path / "Week 46 Files"
        assert plan.moving == [quest_path, run]
        assert plan.staying == [("Board Check.prcss", "a template, not run yet")]

        pdf = publish_process(quest, quest_path)

        folder = tmp_path / "Week 46 Files"
        assert sorted(p.name for p in tmp_path.iterdir() if p != logs_dir) == ["Board Check.prcss", "Week 46 Files", "Week 46.wrkqstlog.pdf"]
        assert sorted(p.name for p in folder.iterdir()) == sorted([quest_path.name, run.name])
        assert pdf == tmp_path / "Week 46.wrkqstlog.pdf"
        # The kept quest opens with its process still attached, from the folder.
        kept = storage.load_process(folder / quest_path.name)
        assert kept.steps[1].linked_process_path == str(folder / run.name)
        assert kept.steps[2].linked_process_path == str(template)
        assert storage.load_process(folder / run.name).name == "Board Check"

    def test_a_second_log_of_the_same_name_gets_its_own_folder(self, tmp_path, logs_dir):
        (tmp_path / "Week 46 Files").mkdir()
        quest_path = tmp_path / "Week 46#COMPLETE.wrkqst"
        save_process(_quest(""), quest_path)
        publish_process(_quest(""), quest_path)
        assert (tmp_path / "Week 46 Files (2)" / quest_path.name).exists()

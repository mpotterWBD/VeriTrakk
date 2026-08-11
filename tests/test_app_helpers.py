from __future__ import annotations

from src.app import (
    LogFileTree,
    PrcssFileTree,
    ProcessFileTree,
    WorkQuestFileTree,
    _builder_label,
    _progress_bar,
    _step_label,
)
from src.storage import Step


# ── _progress_bar ─────────────────────────────────────────────────────────────

class TestProgressBar:
    def test_zero_percent_is_empty(self):
        assert _progress_bar(0) == "░" * 20

    def test_hundred_percent_is_full(self):
        assert _progress_bar(100) == "█" * 20

    def test_fifty_percent_is_half(self):
        bar = _progress_bar(50)
        assert bar == "█" * 10 + "░" * 10

    def test_custom_width(self):
        bar = _progress_bar(50, width=10)
        assert len(bar) == 10
        assert bar == "█" * 5 + "░" * 5

    def test_rounds_to_nearest_block(self):
        # 33% of 10 = 3.3 -> rounds to 3 filled blocks.
        bar = _progress_bar(33, width=10)
        assert bar.count("█") == 3


# ── _step_label ───────────────────────────────────────────────────────────────

class TestStepLabel:
    def test_pending_step_shows_open_circle(self):
        step = Step(label="Do the thing", level=1)
        text = _step_label(step)
        assert text.plain.startswith("○  Do the thing")

    def test_pending_step_with_threshold_shows_marker(self):
        step = Step(label="Measure", level=1, threshold_upper="10")
        text = _step_label(step)
        assert "⊙" in text.plain

    def test_pending_step_with_note_shows_marker(self):
        step = Step(label="Task", level=1, note="a note")
        text = _step_label(step)
        assert "\xb7" in text.plain

    def test_in_progress_step_shows_half_circle(self):
        step = Step(label="Task", level=1, started=True)
        text = _step_label(step)
        assert text.plain.startswith("◔  Task")

    def test_paused_step_shows_paused_label(self):
        step = Step(label="Task", level=1, started=True, paused=True)
        text = _step_label(step)
        assert "PAUSED" in text.plain

    def test_completed_step_without_result_shows_checkmark(self):
        step = Step(label="Task", level=1, completed=True)
        text = _step_label(step)
        assert text.plain.startswith("✓  Task")
        assert "PASS" not in text.plain
        assert "FAIL" not in text.plain

    def test_completed_pass_result_appends_pass(self):
        step = Step(label="Task", level=1, completed=True, result="PASS")
        text = _step_label(step)
        assert "PASS" in text.plain
        assert text.plain.startswith("✓")

    def test_completed_fail_result_appends_fail_with_x_mark(self):
        step = Step(label="Task", level=1, completed=True, result="FAIL")
        text = _step_label(step)
        assert text.plain.startswith("✗")
        assert "FAIL" in text.plain

    def test_main_quest_wraps_label_in_bangs(self):
        step = Step(label="Important", level=1, main_quest=True)
        text = _step_label(step)
        assert "!!! Important !!!" in text.plain

    def test_process_badge_shown_for_linked_process(self):
        step = Step(label="Linked", level=1, linked_process_path="other.prcss")
        text = _step_label(step, show_process_badge=True)
        assert text.plain.startswith("○  [P] Linked")

    def test_process_badge_hidden_when_flag_false(self):
        step = Step(label="Linked", level=1, linked_process_path="other.prcss")
        text = _step_label(step, show_process_badge=False)
        assert "[P]" not in text.plain

    def test_number_prefix_included(self):
        step = Step(label="Task", level=1)
        text = _step_label(step, number_prefix="1.")
        assert "1. Task" in text.plain

    def test_live_seconds_shown_for_in_progress_step(self):
        step = Step(label="Task", level=1, started=True)
        text = _step_label(step, live_seconds=3725)   # 1h 2m 5s
        assert "01:02:05" in text.plain

    def test_sub_progress_shown_for_in_progress_parent(self):
        step = Step(label="Task", level=1, started=True)
        text = _step_label(step, sub_done=2, sub_total=5)
        assert "(2/5)" in text.plain


# ── _builder_label ────────────────────────────────────────────────────────────

class TestBuilderLabel:
    def test_top_level_has_no_indent(self):
        step = Step(label="Top", level=1)
        text = _builder_label(step)
        assert text.plain == "Top"

    def test_nested_level_indents(self):
        step = Step(label="Nested", level=3)
        text = _builder_label(step)
        assert text.plain.startswith("    Nested")   # 2 levels * 2 spaces

    def test_threshold_badge(self):
        step = Step(label="Task", level=1, threshold_upper="5")
        text = _builder_label(step)
        assert "[T]" in text.plain

    def test_manual_pass_fail_badge(self):
        step = Step(label="Task", level=1, manual_pass_fail=True)
        text = _builder_label(step)
        assert "[B]" in text.plain

    def test_requires_text_input_badge(self):
        step = Step(label="Task", level=1, requires_text_input=True)
        text = _builder_label(step)
        assert "[I]" in text.plain

    def test_linked_process_badge(self):
        step = Step(label="Task", level=1, linked_process_path="x.prcss")
        text = _builder_label(step)
        assert "[L]" in text.plain

    def test_main_quest_badge(self):
        step = Step(label="Task", level=1, main_quest=True)
        text = _builder_label(step)
        assert "[M]" in text.plain

    def test_no_badges_when_no_flags_set(self):
        step = Step(label="Plain", level=1)
        text = _builder_label(step)
        assert text.plain == "Plain"

    def test_multiple_badges_all_present(self):
        step = Step(label="Task", level=1, threshold_upper="5", manual_pass_fail=True, main_quest=True)
        text = _builder_label(step)
        assert "[T]" in text.plain
        assert "[B]" in text.plain
        assert "[M]" in text.plain


# ── DirectoryTree subclasses' filter_paths ───────────────────────────────────

def _make_paths(tmp_path, names):
    paths = []
    for name in names:
        p = tmp_path / name
        p.write_text("", encoding="utf-8")
        paths.append(p)
    return paths


class TestProcessFileTreeFilter:
    def test_includes_prcss_and_wrkqst_excludes_completed(self, tmp_path):
        tree = ProcessFileTree(tmp_path)
        paths = _make_paths(tmp_path, ["a.prcss", "b.wrkqst", "c.txt", "d#COMPLETE.prcss"])
        result = tree.filter_paths(paths)
        names = {p.name for p in result}
        assert names == {"a.prcss", "b.wrkqst"}

    def test_includes_directories(self, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        tree = ProcessFileTree(tmp_path)
        result = tree.filter_paths([subdir])
        assert subdir in result


class TestPrcssFileTreeFilter:
    def test_only_prcss_files(self, tmp_path):
        tree = PrcssFileTree(tmp_path)
        paths = _make_paths(tmp_path, ["a.prcss", "b.wrkqst", "c#COMPLETE.prcss"])
        result = tree.filter_paths(paths)
        names = {p.name for p in result}
        assert names == {"a.prcss"}


class TestWorkQuestFileTreeFilter:
    def test_only_wrkqst_files(self, tmp_path):
        tree = WorkQuestFileTree(tmp_path)
        paths = _make_paths(tmp_path, ["a.prcss", "b.wrkqst", "c#COMPLETE.wrkqst"])
        result = tree.filter_paths(paths)
        names = {p.name for p in result}
        assert names == {"b.wrkqst"}


class TestLogFileTreeFilter:
    def test_shows_logs_and_completed_source_files(self, tmp_path):
        tree = LogFileTree(tmp_path)
        paths = _make_paths(
            tmp_path,
            ["a.prcsslog", "b.wrkqstlog", "c#COMPLETE.prcss", "d.prcss", "e.txt"],
        )
        result = tree.filter_paths(paths)
        names = {p.name for p in result}
        assert names == {"a.prcsslog", "b.wrkqstlog", "c#COMPLETE.prcss"}

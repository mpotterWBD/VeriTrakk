from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src import storage
from src.storage import (
    Process,
    Step,
    create_process_instance,
    generate_log_pdf_bytes,
    generate_log_text,
    is_base_process,
    load_process,
    load_session,
    publish_process,
    sanitize_filename,
    sanitize_filename_for,
    save_process,
    save_session,
)


# ── Step ─────────────────────────────────────────────────────────────────────

class TestStepHasThreshold:
    def test_no_thresholds(self):
        assert Step(label="x", level=1).has_threshold() is False

    def test_upper_only(self):
        assert Step(label="x", level=1, threshold_upper="10").has_threshold() is True

    def test_lower_only(self):
        assert Step(label="x", level=1, threshold_lower="0").has_threshold() is True

    def test_both(self):
        step = Step(label="x", level=1, threshold_upper="10", threshold_lower="0")
        assert step.has_threshold() is True


# ── Process tree navigation ──────────────────────────────────────────────────

def _build_tree_process() -> Process:
    """
    0 A            (level 1)
    1   A1         (level 2)
    2     A1a      (level 3)
    3   A2         (level 2)
    4 B            (level 1)
    5   B1         (level 2)
    """
    labels_levels = [
        ("A", 1), ("A1", 2), ("A1a", 3), ("A2", 2), ("B", 1), ("B1", 2),
    ]
    steps = [Step(label=label, level=level) for label, level in labels_levels]
    return Process(name="Tree Proc", steps=steps)


class TestProcessTopLevelProperties:
    def test_top_steps(self):
        proc = _build_tree_process()
        assert [i for i, _ in proc.top_steps] == [0, 4]
        assert [s.label for _, s in proc.top_steps] == ["A", "B"]

    def test_total_top(self):
        assert _build_tree_process().total_top == 2

    def test_done_top_counts_only_completed_top_level(self):
        proc = _build_tree_process()
        proc.steps[0].completed = True   # A (top-level)
        proc.steps[1].completed = True   # A1 (nested, shouldn't count)
        assert proc.done_top == 1

    def test_progress_pct(self):
        proc = _build_tree_process()
        assert proc.progress_pct == 0.0
        proc.steps[0].completed = True
        assert proc.progress_pct == 50.0
        proc.steps[4].completed = True
        assert proc.progress_pct == 100.0

    def test_progress_pct_with_no_steps_is_zero(self):
        assert Process(name="Empty").progress_pct == 0.0


class TestIsFullyComplete:
    def test_empty_process_is_not_complete(self):
        assert Process(name="Empty").is_fully_complete() is False

    def test_incomplete_top_level(self):
        proc = _build_tree_process()
        proc.steps[0].completed = True
        assert proc.is_fully_complete() is False

    def test_all_top_level_complete(self):
        proc = _build_tree_process()
        proc.steps[0].completed = True
        proc.steps[4].completed = True
        # Nested steps being incomplete doesn't matter for this check.
        assert proc.is_fully_complete() is True


class TestParentOf:
    def test_top_level_step_has_no_parent(self):
        proc = _build_tree_process()
        assert proc.parent_of(0) is None

    def test_direct_child(self):
        proc = _build_tree_process()
        assert proc.parent_of(1) == 0   # A1 -> A
        assert proc.parent_of(3) == 0   # A2 -> A
        assert proc.parent_of(5) == 4   # B1 -> B

    def test_grandchild_finds_nearest_shallower_ancestor(self):
        proc = _build_tree_process()
        assert proc.parent_of(2) == 1   # A1a -> A1 (nearest, not A)

    def test_out_of_range_returns_none(self):
        proc = _build_tree_process()
        assert proc.parent_of(-1) is None
        assert proc.parent_of(999) is None


class TestSubtreeEndExclusive:
    def test_top_level_subtree_spans_all_descendants(self):
        proc = _build_tree_process()
        assert proc.subtree_end_exclusive(0) == 4   # A's subtree ends before B
        assert proc.subtree_end_exclusive(4) == 6   # B's subtree ends at list end

    def test_nested_subtree(self):
        proc = _build_tree_process()
        assert proc.subtree_end_exclusive(1) == 3   # A1's subtree ends before A2

    def test_leaf_subtree_is_just_itself(self):
        proc = _build_tree_process()
        assert proc.subtree_end_exclusive(2) == 3   # A1a has no children

    def test_out_of_range_returns_idx_unchanged(self):
        proc = _build_tree_process()
        assert proc.subtree_end_exclusive(-1) == -1
        assert proc.subtree_end_exclusive(999) == 999


class TestDescendantsAndChildren:
    def test_descendants_of_includes_all_depths(self):
        proc = _build_tree_process()
        idxs = [i for i, _ in proc.descendants_of(0)]
        assert idxs == [1, 2, 3]   # A1, A1a, A2

    def test_children_of_only_immediate_level(self):
        proc = _build_tree_process()
        idxs = [i for i, _ in proc.children_of(0)]
        assert idxs == [1, 3]   # A1, A2 -- not A1a

    def test_children_of_leaf_is_empty(self):
        proc = _build_tree_process()
        assert proc.children_of(2) == []

    def test_descendants_out_of_range_is_empty(self):
        proc = _build_tree_process()
        assert proc.descendants_of(-1) == []
        assert proc.descendants_of(999) == []


class TestHasChildren:
    def test_true_for_parent(self):
        proc = _build_tree_process()
        assert proc.has_children(0) is True   # A
        assert proc.has_children(1) is True   # A1

    def test_false_for_leaf(self):
        proc = _build_tree_process()
        assert proc.has_children(2) is False   # A1a
        assert proc.has_children(5) is False   # B1

    def test_out_of_range_is_false(self):
        proc = _build_tree_process()
        assert proc.has_children(999) is False


class TestLastDescendantIdx:
    def test_parent_with_nested_children(self):
        proc = _build_tree_process()
        assert proc.last_descendant_idx(0) == 3   # A -> A2 (last of A1/A1a/A2)

    def test_leaf_is_itself(self):
        proc = _build_tree_process()
        assert proc.last_descendant_idx(2) == 2

    def test_last_top_level_step(self):
        proc = _build_tree_process()
        assert proc.last_descendant_idx(4) == 5   # B -> B1


# ── Clock accounting ─────────────────────────────────────────────────────────

class TestTotalClockSeconds:
    def test_no_events_no_adjust(self):
        proc = Process(name="WQ", kind="work_quest")
        assert proc.total_clock_seconds() == 0

    def test_single_in_out_pair(self):
        start = datetime(2026, 1, 1, 9, 0, 0)
        end = datetime(2026, 1, 1, 9, 30, 0)
        proc = Process(
            name="WQ",
            kind="work_quest",
            clock_events=[f"IN|{start.isoformat()}", f"OUT|{end.isoformat()}"],
        )
        assert proc.total_clock_seconds() == 1800

    def test_multiple_pairs_sum(self):
        proc = Process(
            name="WQ",
            kind="work_quest",
            clock_events=[
                "IN|2026-01-01T09:00:00", "OUT|2026-01-01T09:10:00",   # 600s
                "IN|2026-01-01T10:00:00", "OUT|2026-01-01T10:05:00",   # 300s
            ],
        )
        assert proc.total_clock_seconds() == 900

    def test_clock_adjust_seconds_added(self):
        proc = Process(name="WQ", kind="work_quest", clock_adjust_seconds=120)
        assert proc.total_clock_seconds() == 120

    def test_negative_adjust_cannot_go_below_zero(self):
        proc = Process(name="WQ", kind="work_quest", clock_adjust_seconds=-500)
        assert proc.total_clock_seconds() == 0

    def test_malformed_events_are_skipped(self):
        proc = Process(
            name="WQ",
            kind="work_quest",
            clock_events=["not-a-valid-event", "IN|garbage-timestamp", "OUT|2026-01-01T10:00:00"],
        )
        assert proc.total_clock_seconds() == 0

    def test_unmatched_trailing_in_without_out_contributes_nothing_when_not_clocked_in(self):
        proc = Process(
            name="WQ",
            kind="work_quest",
            clocked_in=False,
            clock_events=["IN|2026-01-01T09:00:00"],
        )
        assert proc.total_clock_seconds() == 0

    def test_active_clock_in_window_counts_toward_now(self):
        active_since = datetime.now() - timedelta(seconds=10)
        proc = Process(
            name="WQ",
            kind="work_quest",
            clocked_in=True,
            clock_active_since=active_since.isoformat(),
        )
        seconds = proc.total_clock_seconds()
        # Allow slack for test execution time.
        assert 9 <= seconds <= 30

    def test_total_clock_minutes_floors(self):
        proc = Process(name="WQ", kind="work_quest", clock_adjust_seconds=125)
        assert proc.total_clock_minutes() == 2


# ── CSV persistence round trip ───────────────────────────────────────────────

class TestSaveLoadProcessRoundTrip:
    def test_basic_round_trip(self, tmp_path):
        proc = Process(
            name="Round Trip Proc",
            kind="process",
            spawn_instances=True,
            steps=[
                Step(label="Step One", level=1, completed=True, completed_at="2026-01-01T10:00:00", result="PASS"),
                Step(label="Sub One", level=2, note="a note", threshold_upper="10.5", threshold_lower="-2"),
            ],
        )
        path = tmp_path / "roundtrip.prcss"
        save_process(proc, path)
        loaded = load_process(path)

        assert loaded.name == proc.name
        assert loaded.kind == proc.kind
        assert loaded.spawn_instances == proc.spawn_instances
        assert len(loaded.steps) == 2
        assert loaded.steps[0].label == "Step One"
        assert loaded.steps[0].completed is True
        assert loaded.steps[0].result == "PASS"
        assert loaded.steps[1].note == "a note"
        assert loaded.steps[1].threshold_upper == "10.5"
        assert loaded.steps[1].threshold_lower == "-2"

    def test_work_quest_clock_fields_round_trip(self, tmp_path):
        proc = Process(
            name="WQ",
            kind="work_quest",
            clocked_in=True,
            clock_active_since="2026-01-01T09:00:00",
            clock_events=["IN|2026-01-01T09:00:00"],
            clock_adjust_seconds=42,
        )
        path = tmp_path / "wq.wrkqst"
        save_process(proc, path)
        loaded = load_process(path)

        assert loaded.kind == "work_quest"
        assert loaded.clocked_in is True
        assert loaded.clock_active_since == "2026-01-01T09:00:00"
        assert loaded.clock_events == ["IN|2026-01-01T09:00:00"]
        assert loaded.clock_adjust_seconds == 42

    def test_boolean_step_flags_round_trip(self, tmp_path):
        proc = Process(
            name="Flags",
            steps=[
                Step(
                    label="Flagged",
                    level=1,
                    manual_pass_fail=True,
                    requires_text_input=True,
                    main_quest=True,
                    captured_text_input="hello",
                    linked_process_path="other.prcss",
                ),
            ],
        )
        path = tmp_path / "flags.prcss"
        save_process(proc, path)
        loaded = load_process(path)

        step = loaded.steps[0]
        assert step.manual_pass_fail is True
        assert step.requires_text_input is True
        assert step.main_quest is True
        assert step.captured_text_input == "hello"
        assert step.linked_process_path == "other.prcss"

    def test_duration_seconds_derived_from_minutes_when_absent(self, tmp_path):
        # Simulates an older CSV written before duration_seconds existed.
        path = tmp_path / "legacy_minutes.prcss"
        path.write_text(
            "kind,spawn_instances,clocked_in,clock_active_since,clock_events,clock_adjust_seconds,"
            "level,label,completed,completed_at,started,started_at,paused,active_since,"
            "duration_minutes,duration_seconds,note,threshold_upper,threshold_lower,"
            "manual_pass_fail,requires_text_input,captured_text_input,result,linked_process_path,main_quest\n"
            "process,True,,,,,0,Proc,False,,,,,,,,,,,,,,,,\n"
            ",,,,,,1,Task,False,,False,,False,,5,,,,,False,False,,,,False\n",
            encoding="utf-8",
        )
        loaded = load_process(path)
        assert loaded.steps[0].duration_minutes == 5
        assert loaded.steps[0].duration_seconds == 300

    def test_save_creates_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "proc.prcss"
        save_process(Process(name="Nested"), path)
        assert path.exists()


class TestLoadCsvFallsBackToLegacy:
    def test_non_csv_file_uses_legacy_parser(self, tmp_path):
        path = tmp_path / "old.prcss"
        path.write_text(
            "Legacy Proc\n"
            "[S]|Step One|[d=20260115_093000]|[n=Note here][UT=10][LT=2][PASS]\n"
            "[>]|Step One Sub|[d=20260115_094500]\n"
            "Step Two\n",
            encoding="utf-8",
        )
        proc = load_process(path)

        assert proc.name == "Legacy Proc"
        assert proc.completed is False
        assert len(proc.steps) == 3

        step_one = proc.steps[0]
        assert step_one.label == "Step One"
        assert step_one.level == 1
        assert step_one.completed is True
        assert step_one.completed_at == "2026-01-15T09:30:00"
        assert step_one.note == "Note here"
        assert step_one.threshold_upper == "10"
        assert step_one.threshold_lower == "2"
        assert step_one.result == "PASS"

        sub = proc.steps[1]
        assert sub.label == "Step One Sub"
        assert sub.level == 2
        assert sub.completed is False
        assert sub.completed_at == "2026-01-15T09:45:00"

        step_two = proc.steps[2]
        assert step_two.label == "Step Two"
        assert step_two.level == 1
        assert step_two.completed is False

    def test_completed_root_process(self, tmp_path):
        path = tmp_path / "old2.prcss"
        path.write_text("[S]|Completed Proc|[d=20260101_000000]\nOnly Step\n", encoding="utf-8")
        proc = load_process(path)
        assert proc.name == "Completed Proc"
        assert proc.completed is True
        assert proc.completed_at == "2026-01-01T00:00:00"

    def test_legacy_work_quest_extension_sets_kind(self, tmp_path):
        path = tmp_path / "old.wrkqst"
        path.write_text("Legacy Quest\nTask\n", encoding="utf-8")
        proc = load_process(path)
        assert proc.kind == "work_quest"

    def test_empty_file_yields_unnamed_process(self, tmp_path):
        path = tmp_path / "empty.prcss"
        path.write_text("", encoding="utf-8")
        proc = load_process(path)
        assert proc.name == "Unnamed Process"
        assert proc.steps == []

    def test_fail_result_and_bad_timestamp_falls_back_to_raw(self, tmp_path):
        path = tmp_path / "old3.prcss"
        path.write_text("Proc\n[S]|Bad TS|[d=not-a-timestamp][FAIL]\n", encoding="utf-8")
        proc = load_process(path)
        step = proc.steps[0]
        assert step.result == "FAIL"
        # Unparseable timestamp is kept verbatim rather than raising.
        assert step.completed_at == "not-a-timestamp"


# ── Session persistence ───────────────────────────────────────────────────────

class TestSessionPersistence:
    def test_save_then_load_round_trip(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        monkeypatch.setattr(storage, "DATA_DIR", data_dir)
        monkeypatch.setattr(storage, "SESSION_FILE", data_dir / "session.json")

        save_session(tmp_path / "my_dir", "my_file.prcss")
        result = load_session()

        assert result == (tmp_path / "my_dir", "my_file.prcss")

    def test_load_session_missing_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage, "SESSION_FILE", tmp_path / "does_not_exist.json")
        assert load_session() is None

    def test_load_session_corrupt_json_returns_none(self, tmp_path, monkeypatch):
        session_file = tmp_path / "session.json"
        session_file.write_text("not json{{{", encoding="utf-8")
        monkeypatch.setattr(storage, "SESSION_FILE", session_file)
        assert load_session() is None


# ── File naming helpers ──────────────────────────────────────────────────────

class TestSanitizeFilename:
    def test_plain_name_gets_prcss_extension(self):
        assert sanitize_filename("My Process") == "My Process.prcss"

    def test_forbidden_characters_replaced(self):
        assert sanitize_filename('Bad:Name/Here') == "Bad_Name_Here.prcss"

    def test_consecutive_forbidden_chars_collapse_to_one_underscore(self):
        assert sanitize_filename("Weird***Name") == "Weird_Name.prcss"

    def test_empty_name_falls_back_to_default(self):
        assert sanitize_filename("") == "new_process.prcss"

    def test_whitespace_only_name_falls_back_to_default(self):
        assert sanitize_filename("   ") == "new_process.prcss"


class TestSanitizeFilenameFor:
    def test_work_quest_extension(self):
        assert sanitize_filename_for("My Quest", "work_quest") == "My Quest.wrkqst"

    def test_process_extension(self):
        assert sanitize_filename_for("My Proc", "process") == "My Proc.prcss"

    def test_empty_name_falls_back_with_correct_extension(self):
        assert sanitize_filename_for("", "work_quest") == "new_process.wrkqst"


class TestIsBaseProcess:
    def test_plain_prcss_is_base(self):
        assert is_base_process(Path("foo.prcss")) is True

    def test_spawned_instance_is_not_base(self):
        assert is_base_process(Path("foo[Run1]#2026-01-01_00-00-00.prcss")) is False

    def test_wrong_suffix_is_not_base(self):
        assert is_base_process(Path("foo.wrkqst")) is False


class TestCreateProcessInstance:
    def test_creates_timestamped_copy_without_run_id(self, tmp_path):
        base = tmp_path / "base.prcss"
        base.write_text("original content", encoding="utf-8")

        instance = create_process_instance(base)

        assert instance.exists()
        assert instance != base
        assert instance.name.startswith("base#")
        assert instance.suffix == ".prcss"
        assert instance.read_text(encoding="utf-8") == "original content"

    def test_creates_instance_with_run_id_tag(self, tmp_path):
        base = tmp_path / "base.prcss"
        base.write_text("x", encoding="utf-8")

        instance = create_process_instance(base, run_id="Run 1")

        assert "[Run 1]" in instance.name
        assert instance.name.startswith("base[Run 1]#")

    def test_run_id_forbidden_characters_are_sanitized(self, tmp_path):
        base = tmp_path / "base.prcss"
        base.write_text("x", encoding="utf-8")

        instance = create_process_instance(base, run_id="Run/1:Two")

        assert "[Run_1_Two]" in instance.name
        assert "/" not in instance.name.split("[", 1)[1].split("]")[0]


# ── Log text generation ──────────────────────────────────────────────────────

class TestGenerateLogText:
    def test_contains_process_name_and_publish_time(self):
        proc = Process(name="My Proc", steps=[Step(label="Task", level=1, completed=True)])
        published_at = datetime(2026, 1, 15, 14, 30, 0)
        text = generate_log_text(proc, published_at)

        assert "My Proc" in text
        assert "2026-01-15" in text
        assert "PROCESS LOG" in text

    def test_work_quest_uses_work_quest_title_and_hours(self):
        proc = Process(name="My Quest", kind="work_quest", clock_adjust_seconds=3600)
        text = generate_log_text(proc, datetime(2026, 1, 1))
        assert "WORK QUEST LOG" in text
        assert "Total clocked hours" in text
        assert "1.00 h" in text

    def test_step_with_result_shows_pass_fail(self):
        proc = Process(
            name="Proc",
            steps=[Step(label="Task", level=1, completed=True, result="FAIL")],
        )
        text = generate_log_text(proc, datetime(2026, 1, 1))
        assert "[FAIL]" in text
        assert "COMPLETE" in text

    def test_pending_step_shows_pending_status(self):
        proc = Process(name="Proc", steps=[Step(label="Task", level=1)])
        text = generate_log_text(proc, datetime(2026, 1, 1))
        assert "PENDING" in text

    def test_note_included(self):
        proc = Process(name="Proc", steps=[Step(label="Task", level=1, note="Remember this")])
        text = generate_log_text(proc, datetime(2026, 1, 1))
        assert "Remember this" in text

    def test_threshold_included(self):
        proc = Process(
            name="Proc",
            steps=[Step(label="Task", level=1, threshold_upper="10", threshold_lower="1")],
        )
        text = generate_log_text(proc, datetime(2026, 1, 1))
        assert "UT=10" in text
        assert "LT=1" in text

    def test_footer_completion_counts(self):
        proc = Process(
            name="Proc",
            steps=[
                Step(label="A", level=1, completed=True),
                Step(label="B", level=1, completed=False),
            ],
        )
        text = generate_log_text(proc, datetime(2026, 1, 1))
        assert "1 / 2 top-level tasks completed" in text

    def test_completed_timestamp_shown_when_present(self):
        proc = Process(name="Proc", completed_at="2026-02-01T08:00:00")
        text = generate_log_text(proc, datetime(2026, 1, 1))
        assert "Completed:" in text
        assert "2026-02-01" in text


# ── PDF generation ────────────────────────────────────────────────────────────

class TestGenerateLogPdfBytes:
    def test_produces_valid_pdf_header_and_footer(self):
        proc = Process(name="Proc", steps=[Step(label="Task", level=1, completed=True)])
        pdf_bytes = generate_log_pdf_bytes(proc, datetime(2026, 1, 1))

        assert pdf_bytes.startswith(b"%PDF-1.4")
        assert pdf_bytes.rstrip().endswith(b"%%EOF")

    def test_handles_empty_process_without_crashing(self):
        proc = Process(name="Empty Proc")
        pdf_bytes = generate_log_pdf_bytes(proc, datetime(2026, 1, 1))
        assert pdf_bytes.startswith(b"%PDF-1.4")

    def test_paginates_for_many_steps(self):
        steps = [Step(label=f"Task {i}", level=1, note="x" * 300) for i in range(40)]
        proc = Process(name="Big Proc", steps=steps)
        pdf_bytes = generate_log_pdf_bytes(proc, datetime(2026, 1, 1))
        # A document with this much content should span more than one page object.
        assert pdf_bytes.count(b"/Type /Page ") >= 2 or pdf_bytes.count(b"/Type /Page>>") >= 1
        assert pdf_bytes.startswith(b"%PDF-1.4")

    def test_special_characters_are_escaped_and_do_not_crash(self):
        proc = Process(
            name="Proc",
            steps=[Step(label="Task (with parens) \\ backslash", level=1, note="line1\nline2")],
        )
        pdf_bytes = generate_log_pdf_bytes(proc, datetime(2026, 1, 1))
        assert pdf_bytes.startswith(b"%PDF-1.4")

    def test_long_subtask_label_and_note_do_not_crash_or_produce_invalid_pdf(self):
        # Regression: long subtask text used to overflow (clip past) its
        # container because the box height was pre-guessed with a different
        # wrap width than what actually got rendered.
        proc = Process(
            name="Proc",
            kind="work_quest",
            steps=[
                Step(label="Parent", level=1, completed=True),
                Step(
                    label="A very long subtask label " * 6,
                    level=2, completed=True, completed_at="2026-01-01T00:00:00", duration_minutes=45,
                    note="A very long subtask note that should wrap several times. " * 4,
                ),
            ],
        )
        pdf_bytes = generate_log_pdf_bytes(proc, datetime(2026, 1, 1))
        assert pdf_bytes.startswith(b"%PDF-1.4")
        assert pdf_bytes.rstrip().endswith(b"%%EOF")


# ── PDF text wrapping (_wrap_to_width) ───────────────────────────────────────

class TestWrapToWidth:
    def test_wraps_within_width(self):
        text = "This is a fairly long sentence that should wrap across a few lines without exceeding the given width."
        lines = storage._wrap_to_width(text, font="F1", size=10, width=150)
        assert len(lines) > 1
        for line in lines:
            assert storage._text_width(line, font="F1", size=10) <= 150 + 1e-6

    def test_first_line_width_only_constrains_first_line(self):
        text = "alpha beta gamma delta epsilon zeta"
        lines = storage._wrap_to_width(text, font="F1", size=10, width=200, first_line_width=50)
        assert storage._text_width(lines[0], font="F1", size=10) <= 50 + 1e-6
        assert len(lines) > 1

    def test_hard_breaks_a_single_token_wider_than_the_line(self):
        # A run without spaces (e.g. a long identifier) must not be left to
        # run off the page edge — it gets split by character instead.
        text = "x" * 100
        lines = storage._wrap_to_width(text, font="F1", size=10, width=60)
        assert len(lines) > 1
        for line in lines:
            assert storage._text_width(line, font="F1", size=10) <= 60 + 1e-6
        assert "".join(lines) == text

    def test_empty_text_returns_single_empty_line(self):
        assert storage._wrap_to_width("", font="F1", size=10, width=100) == [""]


# ── publish_process orchestration ────────────────────────────────────────────

class TestPublishProcess:
    def test_writes_text_and_pdf_logs_and_deletes_source(self, tmp_path, monkeypatch):
        logs_dir = tmp_path / "logs"
        monkeypatch.setattr(storage, "LOGS_DIR", logs_dir)

        src_path = tmp_path / "MyProc.prcss"
        src_path.write_text("placeholder", encoding="utf-8")
        proc = Process(name="MyProc", steps=[Step(label="Task", level=1, completed=True)])

        log_path = publish_process(proc, src_path)

        assert log_path == src_path.parent / "MyProc.prcsslog"
        assert log_path.exists()
        assert (src_path.parent / "MyProc.prcsslog.pdf").exists()
        assert (logs_dir / "MyProc.prcsslog").exists()
        assert (logs_dir / "MyProc.prcsslog.pdf").exists()
        assert not src_path.exists()

    def test_work_quest_gets_wrkqstlog_extension(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage, "LOGS_DIR", tmp_path / "logs")
        src_path = tmp_path / "MyQuest.wrkqst"
        src_path.write_text("placeholder", encoding="utf-8")
        proc = Process(name="MyQuest", kind="work_quest")

        log_path = publish_process(proc, src_path)

        assert log_path.name == "MyQuest.wrkqstlog"

    def test_complete_suffix_stripped_from_stem(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage, "LOGS_DIR", tmp_path / "logs")
        src_path = tmp_path / "MyProc#COMPLETE.prcss"
        src_path.write_text("placeholder", encoding="utf-8")
        proc = Process(name="MyProc")

        log_path = publish_process(proc, src_path)

        assert log_path.name == "MyProc.prcsslog"

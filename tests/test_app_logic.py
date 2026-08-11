from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rich.text import Text

from src.app import VeriTrakkApp
from src.storage import Process, Step, save_process


@pytest.fixture
def app():
    """A VeriTrakkApp instance that has not been mounted/run.

    Only methods that don't touch the widget tree (self.query_one,
    self.push_screen, self.notify, self.screen) are safe to call on it.
    """
    return VeriTrakkApp()


def _tree_process(kind: str = "process") -> Process:
    """
    0 A            (level 1)
    1   A1         (level 2)
    2     A1a      (level 3)
    3   A2         (level 2)
    4 B            (level 1)
    """
    labels_levels = [("A", 1), ("A1", 2), ("A1a", 3), ("A2", 2), ("B", 1)]
    steps = [Step(label=label, level=level) for label, level in labels_levels]
    return Process(name="Tree", kind=kind, steps=steps)


# ── _compute_run_tree_metrics ────────────────────────────────────────────────

class TestComputeRunTreeMetrics:
    def test_empty_process_returns_empty_maps(self, app):
        app._process = None
        assert app._compute_run_tree_metrics(datetime.now()) == ({}, {}, {})

    def test_children_map_is_immediate_children_only(self, app):
        app._process = _tree_process()
        children_map, _, _ = app._compute_run_tree_metrics(datetime.now())
        assert children_map[0] == [1, 3]   # A -> A1, A2 (not A1a)
        assert children_map[1] == [2]      # A1 -> A1a
        assert children_map[4] == []       # B has no children

    def test_child_stats_counts_done_vs_total(self, app):
        proc = _tree_process()
        proc.steps[1].completed = True   # A1 done
        app._process = proc
        _, child_stats, _ = app._compute_run_tree_metrics(datetime.now())
        assert child_stats[0] == (1, 2)   # A: 1 of 2 immediate children done

    def test_live_seconds_rolls_up_from_leaves(self, app):
        proc = _tree_process()
        proc.steps[2].duration_seconds = 100   # A1a
        proc.steps[3].duration_seconds = 50    # A2
        app._process = proc
        _, _, live_seconds = app._compute_run_tree_metrics(datetime.now())
        assert live_seconds[2] == 100
        assert live_seconds[1] == 100   # A1 rolls up from A1a
        assert live_seconds[0] == 150   # A rolls up from A1 + A2

    def test_active_work_quest_leaf_adds_elapsed_time(self, app):
        now = datetime.now()
        proc = _tree_process(kind="work_quest")
        active_since = now - timedelta(seconds=30)
        proc.steps[2].started = True
        proc.steps[2].active_since = active_since.isoformat()
        # An open clock-in window covering the active period.
        proc.clock_events = [f"IN|{(now - timedelta(seconds=60)).isoformat()}"]
        app._process = proc

        _, _, live_seconds = app._compute_run_tree_metrics(now)
        assert 25 <= live_seconds[2] <= 35


# ── _work_quest_seconds_between ──────────────────────────────────────────────

class TestWorkQuestSecondsBetween:
    def test_no_clock_events_returns_zero(self, app):
        proc = Process(name="WQ", kind="work_quest")
        result = app._work_quest_seconds_between(proc, "2026-01-01T09:00:00", datetime(2026, 1, 1, 10, 0, 0))
        assert result == 0

    def test_ended_before_started_returns_zero(self, app):
        proc = Process(name="WQ", kind="work_quest")
        result = app._work_quest_seconds_between(proc, "2026-01-01T10:00:00", datetime(2026, 1, 1, 9, 0, 0))
        assert result == 0

    def test_malformed_started_at_returns_zero(self, app):
        proc = Process(name="WQ", kind="work_quest")
        result = app._work_quest_seconds_between(proc, "not-a-date", datetime(2026, 1, 1))
        assert result == 0

    def test_overlap_with_single_clock_window(self, app):
        proc = Process(
            name="WQ",
            kind="work_quest",
            clock_events=["IN|2026-01-01T09:00:00", "OUT|2026-01-01T10:00:00"],
        )
        # Step started at 09:30, ended at 09:45 -- fully inside the clock window.
        result = app._work_quest_seconds_between(
            proc, "2026-01-01T09:30:00", datetime(2026, 1, 1, 9, 45, 0)
        )
        assert result == 900

    def test_partial_overlap_is_clipped(self, app):
        proc = Process(
            name="WQ",
            kind="work_quest",
            clock_events=["IN|2026-01-01T09:00:00", "OUT|2026-01-01T09:30:00"],
        )
        # Step spans 09:15-10:00, but clock-in window ends at 09:30.
        result = app._work_quest_seconds_between(
            proc, "2026-01-01T09:15:00", datetime(2026, 1, 1, 10, 0, 0)
        )
        assert result == 900   # only 09:15-09:30 counts

    def test_unmatched_trailing_in_treated_as_open_until_ended_at(self, app):
        proc = Process(name="WQ", kind="work_quest", clock_events=["IN|2026-01-01T09:00:00"])
        result = app._work_quest_seconds_between(
            proc, "2026-01-01T09:00:00", datetime(2026, 1, 1, 9, 10, 0)
        )
        assert result == 600

    def test_minutes_variant_divides_by_sixty(self, app):
        proc = Process(
            name="WQ",
            kind="work_quest",
            clock_events=["IN|2026-01-01T09:00:00", "OUT|2026-01-01T09:02:30"],
        )
        result = app._work_quest_minutes_between(
            proc, "2026-01-01T09:00:00", datetime(2026, 1, 1, 9, 2, 30)
        )
        assert result == 2   # 150 seconds // 60


# ── _sync_parent_states_for_process ──────────────────────────────────────────

class TestSyncParentStatesForProcess:
    def test_parent_incomplete_when_a_child_is_incomplete(self, app):
        proc = _tree_process()
        proc.steps[3].completed = True   # A2 done, A1/A1a not
        app._sync_parent_states_for_process(proc)
        assert proc.steps[0].completed is False   # A

    def test_parent_completed_when_all_children_done(self, app):
        proc = Process(
            name="P",
            steps=[
                Step(label="Parent", level=1),
                Step(label="C1", level=2, completed=True, completed_at="2026-01-01T09:00:00"),
                Step(label="C2", level=2, completed=True, completed_at="2026-01-01T10:00:00"),
            ],
        )
        app._sync_parent_states_for_process(proc)
        assert proc.steps[0].completed is True
        assert proc.steps[0].completed_at == "2026-01-01T10:00:00"   # max of children

    def test_parent_paused_when_in_progress_child_is_paused_and_none_active(self, app):
        proc = Process(
            name="P",
            steps=[
                Step(label="Parent", level=1),
                Step(label="C1", level=2, started=True, paused=True),
            ],
        )
        app._sync_parent_states_for_process(proc)
        assert proc.steps[0].started is True
        assert proc.steps[0].paused is True

    def test_parent_duration_sums_children(self, app):
        proc = Process(
            name="P",
            steps=[
                Step(label="Parent", level=1),
                Step(label="C1", level=2, duration_seconds=120),
                Step(label="C2", level=2, duration_seconds=60),
            ],
        )
        app._sync_parent_states_for_process(proc)
        assert proc.steps[0].duration_seconds == 180
        assert proc.steps[0].duration_minutes == 3

    def test_leaf_steps_are_untouched(self, app):
        proc = Process(name="P", steps=[Step(label="Leaf", level=1, note="keep me")])
        app._sync_parent_states_for_process(proc)
        assert proc.steps[0].note == "keep me"

    def test_multi_level_rollup_propagates_to_grandparent(self, app):
        proc = _tree_process()
        # Complete the leaf grandchild; parent (A1) and grandparent (A) should
        # both derive completed status once every descendant reports done.
        proc.steps[2].completed = True   # A1a
        proc.steps[2].completed_at = "2026-01-01T09:00:00"
        proc.steps[3].completed = True   # A2
        proc.steps[3].completed_at = "2026-01-01T09:05:00"
        app._sync_parent_states_for_process(proc)
        assert proc.steps[1].completed is True   # A1 (only child A1a, now done)
        assert proc.steps[0].completed is True   # A (children A1 + A2, both done)


# ── _active_step_idx ──────────────────────────────────────────────────────────

class TestActiveStepIdx:
    def test_no_process_returns_none(self, app):
        app._process = None
        assert app._active_step_idx() is None

    def test_no_active_leaf_returns_none(self, app):
        app._process = _tree_process()
        assert app._active_step_idx() is None

    def test_finds_started_unpaused_leaf(self, app):
        proc = _tree_process()
        proc.steps[2].started = True   # A1a, a leaf
        app._process = proc
        assert app._active_step_idx() == 2

    def test_parent_with_children_never_counted_as_active(self, app):
        proc = _tree_process()
        proc.steps[0].started = True   # A has children -- derived state, ignored
        app._process = proc
        assert app._active_step_idx() is None

    def test_completed_step_is_not_active(self, app):
        proc = _tree_process()
        proc.steps[2].started = True
        proc.steps[2].completed = True
        app._process = proc
        assert app._active_step_idx() is None

    def test_paused_step_is_not_active(self, app):
        proc = _tree_process()
        proc.steps[2].started = True
        proc.steps[2].paused = True
        app._process = proc
        assert app._active_step_idx() is None

    def test_exclude_idx_skips_that_step(self, app):
        proc = _tree_process()
        proc.steps[2].started = True
        app._process = proc
        assert app._active_step_idx(exclude_idx=2) is None


# ── _format_minutes / _format_seconds ────────────────────────────────────────

class TestFormatMinutesSeconds:
    def test_format_minutes_pads_and_splits_hours(self, app):
        assert app._format_minutes(125) == "02:05"

    def test_format_minutes_negative_hours_clamped_but_python_modulo_leaks_through(self, app):
        # h = max(0, -5 // 60) = max(0, -1) = 0, but Python's modulo on a
        # negative dividend returns a positive remainder: -5 % 60 == 55.
        # The max(0, ...) guard on `m` never actually triggers as a result.
        assert app._format_minutes(-5) == "00:55"


class TestBindingGuards:
    def test_back_to_work_quest_is_available_after_build_editing(self, app):
        app._mode = "build"
        app._return_wq_path = Path("work_quest.wrkqst")
        assert app.check_action("back_to_work_quest", ()) is True

    def test_return_context_status_text_shows_work_quest_name(self, app):
        app._return_wq_path = Path("linked_work_quest.wrkqst")
        t = Text()
        app._append_return_context_status(t)
        assert "linked_work_quest.wrkqst" in t.plain

    def test_complete_step_launches_linked_process_for_linked_work_quest_task(self, app, monkeypatch, tmp_path):
        linked_path = tmp_path / "linked.prcss"
        linked_path.write_text("placeholder", encoding="utf-8")
        app._mode = "run"
        app._process = Process(
            name="WQ",
            kind="work_quest",
            steps=[Step(label="Linked Task", level=1, linked_process_path=str(linked_path))],
        )
        app._proc_path = Path("work_quest.wrkqst")
        app._work_quest_actions_locked = lambda: False
        monkeypatch.setattr(app, "query_one", lambda *args, **kwargs: SimpleNamespace(cursor_node=SimpleNamespace(data=0)))
        monkeypatch.setattr(app, "_linked_process_status", lambda step: (False, linked_path))
        launched = {}

        def fake_run_linked_process():
            launched["called"] = True

        monkeypatch.setattr(app, "action_run_linked_process", fake_run_linked_process)

        app.action_complete_step()

        assert launched == {"called": True}

    def test_complete_step_auto_completes_linked_work_quest_task_when_linked_process_done(self, app, monkeypatch, tmp_path):
        linked_path = tmp_path / "linked#COMPLETE.prcss"
        linked_path.write_text("placeholder", encoding="utf-8")
        app._mode = "run"
        app._process = Process(
            name="WQ",
            kind="work_quest",
            steps=[Step(label="Linked Task", level=1, started=True, linked_process_path=str(linked_path))],
        )
        app._proc_path = Path("work_quest.wrkqst")
        app._work_quest_actions_locked = lambda: False
        monkeypatch.setattr(app, "query_one", lambda *args, **kwargs: SimpleNamespace(cursor_node=SimpleNamespace(data=0)))
        monkeypatch.setattr(app, "_linked_process_status", lambda step: (True, linked_path))
        auto_completed = {}

        def fake_auto_complete(step_idx: int) -> bool:
            auto_completed["idx"] = step_idx
            return True

        monkeypatch.setattr(app, "_auto_complete_linked_task", fake_auto_complete)

        app.action_complete_step()

        assert auto_completed == {"idx": 0}

    def test_returning_to_work_quest_auto_completes_linked_task_when_done(self, app, monkeypatch, tmp_path):
        work_quest_path = tmp_path / "work_quest.wrkqst"
        work_quest_path.write_text("placeholder", encoding="utf-8")
        app._return_wq_path = work_quest_path
        app._return_wq_step_idx = 0
        app._process = Process(name="WQ", kind="work_quest", steps=[Step(label="Task", level=1)])
        app._proc_path = work_quest_path

        monkeypatch.setattr(app, "_open_process_file", lambda path: None)
        monkeypatch.setattr(app, "_clear_work_quest_return_context", lambda: None)
        moved_to = []
        app._move_run_cursor_to = lambda idx: moved_to.append(idx)
        auto_completed = {}

        def fake_auto_complete(step_idx: int) -> bool:
            auto_completed["idx"] = step_idx
            return True

        monkeypatch.setattr(app, "_auto_complete_linked_task", fake_auto_complete)

        app.action_back_to_work_quest()

        assert auto_completed == {"idx": 0}
        assert moved_to == []

    def test_format_minutes_multiple_of_sixty_negative_is_fully_zero(self, app):
        assert app._format_minutes(-60) == "00:00"

    def test_format_seconds_hh_mm_ss(self, app):
        assert app._format_seconds(3725) == "01:02:05"

    def test_format_seconds_negative_clamped_to_zero(self, app):
        assert app._format_seconds(-1) == "00:00:00"


# ── Threshold pass/fail logic (_on_threshold_result) ─────────────────────────

class TestOnThresholdResult:
    def _prep(self, app, *, upper="", lower=""):
        proc = Process(
            name="P",
            steps=[Step(label="Measure", level=1, threshold_upper=upper, threshold_lower=lower)],
        )
        app._process = proc
        app._pending_thresh_idx = 0
        app._do_complete = Mock()
        return proc

    def test_value_within_bounds_passes(self, app):
        self._prep(app, upper="10", lower="0")
        app._on_threshold_result("5")
        app._do_complete.assert_called_once_with(0, result="PASS")

    def test_value_above_upper_fails(self, app):
        self._prep(app, upper="10", lower="0")
        app._on_threshold_result("15")
        app._do_complete.assert_called_once_with(0, result="FAIL")

    def test_value_below_lower_fails(self, app):
        self._prep(app, upper="10", lower="0")
        app._on_threshold_result("-1")
        app._do_complete.assert_called_once_with(0, result="FAIL")

    def test_negative_thresholds_pass_correctly(self, app):
        # Regression: negative bounds used to be mishandled.
        self._prep(app, upper="-1", lower="-5")
        app._on_threshold_result("-3")
        app._do_complete.assert_called_once_with(0, result="PASS")

    def test_negative_thresholds_fail_correctly(self, app):
        self._prep(app, upper="-1", lower="-5")
        app._on_threshold_result("-10")
        app._do_complete.assert_called_once_with(0, result="FAIL")

    def test_inverted_bounds_are_auto_swapped(self, app):
        # Upper accidentally entered lower than lower bound.
        self._prep(app, upper="2", lower="10")
        app._on_threshold_result("5")
        app._do_complete.assert_called_once_with(0, result="PASS")

    def test_one_sided_upper_only(self, app):
        self._prep(app, upper="10", lower="")
        app._on_threshold_result("1000")
        app._do_complete.assert_called_once_with(0, result="FAIL")

    def test_one_sided_lower_only(self, app):
        self._prep(app, upper="", lower="5")
        app._on_threshold_result("3")
        app._do_complete.assert_called_once_with(0, result="FAIL")

    def test_no_thresholds_always_passes(self, app):
        self._prep(app, upper="", lower="")
        app._on_threshold_result("-999999")
        app._do_complete.assert_called_once_with(0, result="PASS")

    def test_boundary_values_are_inclusive(self, app):
        self._prep(app, upper="10", lower="0")
        app._on_threshold_result("10")
        app._do_complete.assert_called_once_with(0, result="PASS")

    def test_none_value_is_ignored(self, app):
        self._prep(app, upper="10", lower="0")
        app._on_threshold_result(None)
        app._do_complete.assert_not_called()

    def test_no_pending_index_is_ignored(self, app):
        self._prep(app, upper="10", lower="0")
        app._pending_thresh_idx = -1
        app._on_threshold_result("5")
        app._do_complete.assert_not_called()

    def test_non_numeric_value_is_ignored_but_resets_pending_idx(self, app):
        self._prep(app, upper="10", lower="0")
        app._on_threshold_result("not-a-number")
        app._do_complete.assert_not_called()
        assert app._pending_thresh_idx == -1

    def test_pending_idx_reset_after_call(self, app):
        self._prep(app, upper="10", lower="0")
        app._on_threshold_result("5")
        assert app._pending_thresh_idx == -1


# ── Carry-over helpers ────────────────────────────────────────────────────────

class TestResetCarriedStepState:
    def test_run_state_cleared_but_content_preserved(self, app):
        step = Step(
            label="Task",
            level=1,
            started=True,
            started_at="2026-01-01T09:00:00",
            paused=True,
            active_since="2026-01-01T09:00:00",
            completed=True,
            completed_at="2026-01-01T10:00:00",
            duration_minutes=30,
            duration_seconds=1800,
            note="keep this note",
            threshold_upper="10",
            threshold_lower="0",
            captured_text_input="some input",
            result="PASS",
        )
        reset = app._reset_carried_step_state(step)

        assert reset.started is False
        assert reset.started_at == ""
        assert reset.paused is False
        assert reset.active_since == ""
        assert reset.completed is False
        assert reset.completed_at == ""
        assert reset.duration_minutes == 0
        assert reset.duration_seconds == 0
        assert reset.captured_text_input == ""
        assert reset.result == ""
        # Content fields survive.
        assert reset.label == "Task"
        assert reset.note == "keep this note"
        assert reset.threshold_upper == "10"

    def test_original_step_is_not_mutated(self, app):
        step = Step(label="Task", level=1, completed=True)
        app._reset_carried_step_state(step)
        assert step.completed is True


class TestStepsToForestAndFlatten:
    def test_round_trip_preserves_order_and_levels(self, app):
        steps = [
            Step(label="A", level=1),
            Step(label="A1", level=2),
            Step(label="A1a", level=3),
            Step(label="A2", level=2),
            Step(label="B", level=1),
        ]
        forest = app._steps_to_forest(steps)
        flat = app._flatten_forest(forest)

        assert [s.label for s in flat] == ["A", "A1", "A1a", "A2", "B"]
        assert [s.level for s in flat] == [1, 2, 3, 2, 1]

    def test_forest_structure_nests_children_under_correct_parent(self, app):
        steps = [Step(label="A", level=1), Step(label="A1", level=2), Step(label="B", level=1)]
        forest = app._steps_to_forest(steps)
        assert len(forest) == 2
        assert forest[0]["step"].label == "A"
        assert [c["step"].label for c in forest[0]["children"]] == ["A1"]
        assert forest[1]["step"].label == "B"
        assert forest[1]["children"] == []


class TestMergeForestByParentName:
    def test_matching_parent_label_merges_children_instead_of_duplicating(self, app):
        destination = app._steps_to_forest([
            Step(label="Weekly", level=1),
            Step(label="Old Task", level=2),
        ])
        incoming = app._steps_to_forest([
            Step(label="Weekly", level=1),
            Step(label="New Task", level=2),
        ])
        app._merge_forest_by_parent_name(destination, incoming)

        assert len(destination) == 1   # no duplicate "Weekly" parent
        child_labels = [c["step"].label for c in destination[0]["children"]]
        assert child_labels == ["Old Task", "New Task"]

    def test_non_matching_label_is_appended_as_new_entry(self, app):
        destination = app._steps_to_forest([Step(label="Existing", level=1)])
        incoming = app._steps_to_forest([Step(label="Brand New", level=1)])
        app._merge_forest_by_parent_name(destination, incoming)

        labels = [n["step"].label for n in destination]
        assert labels == ["Existing", "Brand New"]

    def test_leaf_incoming_node_with_no_children_is_appended_not_merged(self, app):
        # Nodes with no children never look for a same-name match; two
        # independent leaves sharing a label both end up in the destination.
        destination = app._steps_to_forest([Step(label="Task", level=1)])
        incoming = app._steps_to_forest([Step(label="Task", level=1)])
        app._merge_forest_by_parent_name(destination, incoming)
        assert len(destination) == 2


# ── _root_template_path ──────────────────────────────────────────────────────

class TestRootTemplatePath:
    def test_non_prcss_suffix_returns_none(self, app, tmp_path):
        assert app._root_template_path(tmp_path / "foo.wrkqst") is None

    def test_no_hash_in_stem_returns_none(self, app, tmp_path):
        assert app._root_template_path(tmp_path / "foo.prcss") is None

    def test_finds_plain_base_template(self, app, tmp_path):
        base = tmp_path / "Foo.prcss"
        save_process(Process(name="Foo", kind="process"), base)
        instance = tmp_path / "Foo#2026-01-01_00-00-00.prcss"

        result = app._root_template_path(instance)
        assert result == base

    def test_finds_bracketed_run_id_base_template(self, app, tmp_path):
        base = tmp_path / "Foo[Run1].prcss"
        save_process(Process(name="Foo", kind="process"), base)
        instance = tmp_path / "Foo[Run1]#2026-01-01_00-00-00.prcss"

        result = app._root_template_path(instance)
        assert result == base

    def test_falls_back_to_unbracketed_base_when_bracketed_missing(self, app, tmp_path):
        base = tmp_path / "Foo.prcss"
        save_process(Process(name="Foo", kind="process"), base)
        instance = tmp_path / "Foo[Run1]#2026-01-01_00-00-00.prcss"

        result = app._root_template_path(instance)
        assert result == base

    def test_no_matching_file_returns_none(self, app, tmp_path):
        instance = tmp_path / "Foo#2026-01-01_00-00-00.prcss"
        assert app._root_template_path(instance) is None

    def test_base_with_wrong_kind_is_rejected(self, app, tmp_path):
        base = tmp_path / "Foo.prcss"
        save_process(Process(name="Foo", kind="work_quest"), base)
        instance = tmp_path / "Foo#2026-01-01_00-00-00.prcss"

        assert app._root_template_path(instance) is None

"""The work quest clock switch must not ping-pong (Nov 2 2026: a clock-out
while a step timer ran turned into 4,374 IN/OUT pairs in 2.5 minutes).

Textual delivers Switch.Changed after the fact, so a redraw that sets the
switch (the once-a-second tick) between a click and its handling left two
opposite messages in flight, each handled one clocking in or out and
redrawing the switch, which queued the next. These tests replay that.
"""
from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest

from src.app import VeriTrakkApp
from src.storage import Process, Step


def _quest_app(tmp_path):
    app = VeriTrakkApp()
    app._mode = "run"
    app._process = Process(name="Quest", kind="work_quest", steps=[Step(label="Task", level=1)])
    app._proc_path = tmp_path / "quest.wrkqst"
    app._process.clocked_in = True
    app._process.clock_events = ["IN|2026-11-02T08:54:31"]
    return app


def _replay(app, events: deque, switch, limit: int = 200) -> int:
    """Hands queued Changed messages to the app like Textual would. Each
    redraw that changes the switch queues another (the real redraw is
    silent now, but this checks the handler copes even if one isn't)."""
    def redraw():
        if switch.value != app._process.clocked_in:
            switch.value = app._process.clocked_in
            events.append(switch.value)

    app._refresh_quest_clock_widgets = redraw
    app._refresh_status = lambda: None
    handled = 0
    while events and handled < limit:
        value = events.popleft()
        app.on_switch_changed(SimpleNamespace(switch=switch, value=value))
        handled += 1
    return handled


def test_click_then_tick_redraw_does_not_loop(tmp_path):
    app = _quest_app(tmp_path)
    switch = SimpleNamespace(id="quest_clock_switch", value=True)
    events: deque = deque()
    # The click: the switch goes off, its message is queued...
    switch.value = False
    events.append(False)
    # ...and before it's handled the tick redraws it from the quest (still in).
    switch.value = True
    events.append(True)
    handled = _replay(app, events, switch)
    assert handled < 10, "the switch's messages kept coming"
    assert len(app._process.clock_events) <= 3


def test_a_plain_click_clocks_out_once(tmp_path):
    app = _quest_app(tmp_path)
    switch = SimpleNamespace(id="quest_clock_switch", value=False)
    _replay(app, deque([False]), switch)
    assert app._process.clocked_in is False
    assert [e.split("|")[0] for e in app._process.clock_events] == ["IN", "OUT"]


def test_toggles_faster_than_anyone_can_click_are_ignored(tmp_path):
    app = _quest_app(tmp_path)
    app._refresh_quest_clock_widgets = lambda: None
    app._refresh_status = lambda: None
    app._toggle_work_quest_clock(False)
    for _ in range(20):
        app._toggle_work_quest_clock(True)
        app._toggle_work_quest_clock(False)
    assert len(app._process.clock_events) == 2   # IN, OUT: the rest came too fast

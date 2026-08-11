# Running the VeriTrakk test suite

This project's tests live in this `tests/` folder and run with `pytest`.
There is no existing test infra elsewhere in the repo to worry about —
`src/test.py` is a stale, unrelated script and is not part of this suite
(pytest is configured to ignore it; see `pytest.ini`).

## 1. Locate / activate the virtual environment

The project already has a virtual environment at `.venv/` in the repo root
(`C:\Users\17195\Desktop\Westbound Designs\veritrakk\.venv`).

- **PowerShell**
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
- **cmd.exe**
  ```cmd
  .venv\Scripts\activate.bat
  ```
- **Or skip activation** and call the venv's Python directly (works from any
  shell, no activation step needed):
  ```
  .venv\Scripts\python.exe -m pytest
  ```

If `.venv` doesn't exist for some reason, create it first:
```
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
```

## 2. Install pytest (one-time, or after a fresh venv)

```
.venv\Scripts\python.exe -m pip install pytest
```

Check it's there:
```
.venv\Scripts\python.exe -m pip show pytest
```

The app itself also needs `textual` installed in the same venv (it already
should be, since it's required to run the app at all):
```
.venv\Scripts\python.exe -m pip install textual
```

## 3. Run the tests

From the **repo root** (`veritrakk/`, the folder containing `src/`, `tests/`,
and `pytest.ini`):

```
.venv\Scripts\python.exe -m pytest
```

Expected result: all tests pass (currently 172 tests, 0 failures). A couple
of harmless `RuntimeWarning`s about an un-awaited `DirectoryTree.watch_path`
coroutine may print — these come from instantiating a Textual widget outside
a running app for unit-testing purposes and are not test failures.

Useful variations:

| Command | What it does |
|---|---|
| `pytest -q` | Quiet output — just dots and a summary |
| `pytest -v` | Verbose — lists every test name and its result |
| `pytest tests/test_storage.py` | Run only one file |
| `pytest tests/test_storage.py::TestSaveLoadProcessRoundTrip` | Run only one test class |
| `pytest -k threshold` | Run only tests whose name matches "threshold" |
| `pytest -x` | Stop at the first failure |
| `pytest --lf` | Re-run only the tests that failed last time |

(If `pytest` is on your PATH inside the activated venv, you can drop the
`.venv\Scripts\python.exe -m ` prefix and just run `pytest ...`.)

## 4. What the suite covers

- `tests/test_storage.py` — the data model and file persistence in
  `src/storage.py`: `Step`/`Process` tree navigation, work-quest clock-time
  math, CSV save/load round-trips, the legacy `.prcss` tag-format parser,
  filename sanitization, spawning process instances, session persistence,
  and text/PDF log generation + publishing.
- `tests/test_app_helpers.py` — pure formatting/filtering helpers in
  `src/app.py`: the progress bar, run-mode and builder-mode step labels, and
  the file-tree filters used by the Open/Build/Logs pickers.
- `tests/test_app_logic.py` — `VeriTrakkApp`'s non-UI business logic: run
  tree metrics, work-quest clock overlap calculations, parent/child state
  derivation, the threshold pass/fail evaluator, and the work-quest
  carry-over merge logic.

These tests never call `VeriTrakkApp().run()` or `python -m src` (that would
launch the real interactive terminal app and hang). They construct
`VeriTrakkApp()` without mounting it and call individual methods directly,
or exercise pure functions from `storage.py` with real files under pytest's
`tmp_path` fixture so nothing touches the real `data/` folder.

## 5. After changing source code

If you modify `src/storage.py` or `src/app.py`, re-run the full suite before
committing:

```
.venv\Scripts\python.exe -m pytest -v
```

If a test fails because you *intentionally* changed behavior, update the
corresponding assertion in the matching `tests/test_*.py` file rather than
deleting the test. If a test fails and the behavior change was
*unintentional*, that's a regression — fix the source, not the test.

## 6. Adding new tests

- New test files go in `tests/` and must be named `test_*.py` for pytest to
  discover them automatically (per `pytest.ini`, only `tests/` is scanned).
- Group related tests into a `class Test...:` with plain `def test_...`
  methods — that's the pattern already used throughout this suite.
- Use the `tmp_path` fixture for anything that touches the filesystem, and
  `monkeypatch` to redirect module-level constants (e.g.
  `storage.DATA_DIR`, `storage.LOGS_DIR`, `storage.SESSION_FILE`) instead of
  writing to the real `data/` folder.
- Prefer testing pure logic (data classes, string/byte builders, `VeriTrakkApp`
  methods that don't call `self.query_one` / `self.push_screen` /
  `self.notify` / `self.screen`) — those can be called directly without
  mounting the app. Methods that touch the live widget tree require
  Textual's `async with app.run_test() as pilot:` harness, which this suite
  currently avoids.

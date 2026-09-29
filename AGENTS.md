# AGENTS.md

## Project
Flask app for labelling images in YOLO format. The shipped code lives in `app/`:
`app/app.py` (~1850 lines) is the entire backend; the UI is plain
`app/templates/index.html` + `app/static/app.js` + `app/static/style.css` with
**no build step**. No package layout, no database. The `data.yaml` reader is
hand-rolled — no PyYAML at runtime. User files live in `YBX_HOME` (below).

## Commands
- Run: `python app/app.py --data /path/to/data.yaml` (optional `--readonly` to
  block writes, `--debug` for verbose browser-console logging, `--home` for a
  custom user folder; `--host`/`--port`, default `127.0.0.1:5000`; Flask runs
  with `debug=True`).
- Install/update: `ybx.sh` (`install` / `upgrade` / `version` / `check-update`);
  e.g. `./ybx.sh install --from .`. It replaces only `<dir>/app/` atomically
  and leaves user files and `.venv` alone. (Replaces the old `install.sh`.)
- Tests (from repo root): `python -m pytest -q`; single test
  `python -m pytest tests/test_app.py::test_name -q`. `pytest.ini` puts `app/`
  on `pythonpath`.
- No lint / format / typecheck config exists.
- Tests import `PIL` (Pillow) but `app/requirements.txt` lists only `Flask`.
  Install Pillow (`pip install pillow`) or collection fails immediately.

## Layout / entrypoints
- `app/app.py` — CLI entry `main()`; module globals `BASE_DIR` (the shipped
  `app/` folder), `YBX_HOME` (the user folder), `STATE` (in-memory dataset
  state), and path constants: shipped `ACTIONS_DIR`, `HOOKS_DIR`, `FILTERS_DIR`,
  `APP_SCRIPT_DIR`, `SHORTCUTS_FILE`; user `USER_ACTIONS_DIR`, `USER_HOOKS_DIR`,
  `USER_FILTERS_DIR`, `USER_SCRIPT_DIR`, `USER_SHORTCUTS_FILE`; state
  `RECENT_FILE`, `VIEW_FILE`. There is deliberately no `SCRIPTS_DIR` symbol:
  scripts are reached relatively (`scripts/…`, since cwd is the home) or as
  `{APP_DIR}/scripts/…`.
- `YBX_HOME` resolution: `--home <dir>` > `$YBX_HOME` > the parent of `app.py`.
  A clone and an install therefore behave the same; the folders are created at
  startup and the path is logged (`[ybe] user dir: …`).
- Extension files ship under `app/` and live (yours) under `YBX_HOME`, same
  names. The user copy is read after the shipped one and wins on a name clash;
  there is no `.a` variant:
  - `actions/*.yaml` — one action per file (`steps`, optional `after_success`,
    optional `name`).
  - `hooks/on_<event>.yaml` — event taken from the filename, else `event_name:`;
    `active: false` skips it.
  - Filters:
    - Contract: `python <filter.py> <data.yaml> <split> <in_pipe> <out_pipe>`; input holds the active split's absolute paths, output feeds the next filter (`run_filter_chain`). Runs with `cwd=YBX_HOME`.
    - UI: Filters button opens a modal with up to 8 stacked selects, run top-to-bottom (`app/static/app.js`).
    - Scratch pipe dir is deleted after each run; `--keep-filter-pipes` keeps it (CLI).
  - `scripts/*.py` — helpers named by action `steps`; the app never scans them.
    Reach them explicitly with `{USER_SCRIPT_DIR}/…` (yours) or
    `{APP_SCRIPT_DIR}/…` (shipped), or relatively as `scripts/…` (cwd is
    `YBX_HOME`).
  - `shortcuts.txt` — `ACTION_NAME <KEY> label`.
- Commands and filters run with `cwd=YBX_HOME` (logged per run) and receive
  `YBE_HOME`, `YBE_APP_DIR`, `YBE_APP_SCRIPT_DIR`, `YBE_USER_SCRIPT_DIR`;
  placeholders include `{APP_DIR}`, `{HOME_DIR}`, `{APP_SCRIPT_DIR}` and
  `{USER_SCRIPT_DIR}`.
- `app/VERSION` and `CHANGELOG.md` (Keep a Changelog); `README.md` /
  `TUTORIAL.md` are user-facing docs.

## Cross-file invariants
- Built-in actions are the `app_*` set in `APP_ACTIONS` (`app/app.py`) and are
  implemented in `app/static/app.js`. Adding/renaming one requires editing both.
- Hook events are `HOOK_EVENTS` (`app/app.py`), fired via `runHook('on_...')` in
  `app/static/app.js`, and documented in `app/hooks/example.yaml` — keep all in
  sync.
- Read-only is enforced server-side (label and tag writes return 403), not only
  in the UI.

## Tests
- `tests/test_app.py` monkeypatches the module-level path constants above
  (shipped and `USER_*`) and resets `STATE`; keep those names module-level so
  tests can patch them.
- Fixtures create real JPEGs (Pillow) in `tmp_path`; tests never touch the repo's
  own `app/actions/`, `shortcuts.txt`, or `.recent_data_yamls.json`.

## Repo conventions & boundaries

- **User standing workflow rules** (embodied here; sources of truth:
  `.roo/rules/Agents.md`):
  - Create/edit a short **plan file per task** under `plans/`; after
    implementing, record implemented/deferred/cancelled in the same file.
  - **Write a git commit after each change.**
  - Each Saturday, ask the user to condense the plans; if approved, summarize
    all completed plans into one file and remove the originals (keep the
    summary short).
  - **Never edit AI rule files yourself** — ask the user to edit them.
  - **Never use or store the user's passwords** unless explicitly asked; if you
    ever see one, give a notice only.
  - The user is a beginner — give advice when asked to do something stupid /
    anti-pattern, and **don't implement blindly**.

- If the public interface changed, update the major version, if you did minor changes , update the minot version.
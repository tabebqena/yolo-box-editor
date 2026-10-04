# AGENTS.md

## Project
Flask app for labelling images in YOLO format. The shipped code lives in `app/`:
`app/app.py` (~3700 lines) is the entire backend; the UI is plain
`app/templates/index.html` + `app/static/app.js` (~4600 lines) +
`app/static/style.css` with **no build step**. No package layout, no database.
The `data.yaml` reader is hand-rolled — no PyYAML at runtime. User files live in
`YBX_HOME` (below).

## Commands
- Run: `python app/app.py --data /path/to/data.yaml` (optional `--readonly` to
  block writes, `--debug` for verbose browser-console logging, `--home` for a
  custom user folder; `--host`/`--port`, default `127.0.0.1:5000`). Other flags:
  `--no-resume` (open Settings instead of the last dataset), `--keep-pipe` and
  `--keep-filter-pipes` (keep scratch pipe files), `--no-update-check`,
  `--log-file`, `--no-reload`. Auth admin commands (run, print and exit):
  `--create-user NAME` (prompts for the password with `getpass`, no echo) and
  `--list-users`. Flask runs with `debug=True`.
- Install/update/remove: `ybx.sh` (`install` / `upgrade` / `update` / `version` /
  `check-update` / `uninstall`); e.g. `./ybx.sh install --from .`. It replaces
  only `<dir>/app/` atomically and leaves user files and `.venv` alone.
  `app/launcher.sh.in` is the `ybe` launcher template (start/stop/restart/status/
  logs) that `ybx.sh` fills in. (Replaces the old `install.sh`.)
- Tests (from repo root): `python -m pytest -q` (~288 tests); single test
  `python -m pytest tests/test_app.py::test_name -q`. `pytest.ini` puts `app/`
  on `pythonpath`.
- No lint / format / typecheck config exists.
- Tests import `PIL` (Pillow) but `app/requirements.txt` lists only `Flask`.
  Install Pillow (`pip install pillow`) or collection fails immediately.

## Layout / entrypoints
- `app/app.py` — CLI entry `main()`; module globals `BASE_DIR` (the shipped
  `app/` folder), `YBX_HOME` (the user folder), `STATE` (in-memory dataset
  state), and path constants: shipped `ACTIONS_DIR`, `HOOKS_DIR`, `FILTERS_DIR`,
  `APP_SCRIPT_DIR`, `SHORTCUTS_FILE`, `VERSION_FILE`, `CHANGES_FILE`; user
  `USER_ACTIONS_DIR`, `USER_HOOKS_DIR`, `USER_FILTERS_DIR`, `USER_SCRIPT_DIR`,
  `USER_SHORTCUTS_FILE`; state files `RECENT_FILE`, `VIEW_FILE`,
  `SETTINGS_FILE`, `UPDATE_CHECK_FILE`, `USERS_FILE` (the login accounts); and
  `FILTER_PIPES_DIR` (temp scratch). Module global `USERS`
  (`{username: password_hash}`) is loaded from `USERS_FILE` at startup; a
  non-empty map turns login on.
  There is deliberately no `SCRIPTS_DIR` symbol: scripts are reached relatively
  (`scripts/…`, since cwd is the home) or as `{APP_DIR}/scripts/…`.
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
    `YBX_HOME`). Shipped helpers: `class_filter.py`, `example.py`,
    `example_filter.py`, `tag_image.py`.
  - `shortcuts.txt` — `ACTION_NAME <KEY> label`.
- Tags: `tags.yaml` beside `data.yaml` (a plain `- tag` list) is the required
  available-tag list; an image's own tags live in a sibling tag file and are
  written with its labels on save (not instantly). The folder is overridable per
  dataset via Settings (`tags_dir`, `POST /api/tags-dir`).
- Commands and filters run with `cwd=YBX_HOME` (logged per run) and receive
  `YBE_HOME`, `YBE_APP_DIR`, `YBE_APP_SCRIPT_DIR`, `YBE_USER_SCRIPT_DIR`;
  placeholders include `{APP_DIR}`, `{HOME_DIR}`, `{APP_SCRIPT_DIR}`,
  `{USER_SCRIPT_DIR}`, `{PYTHON}`, `{PIPE_PATH}` (filters add `{SPLIT}`,
  `{INPUT_PIPE}`, `{OUTPUT_PIPE}`).
- Settings → Actions / Hooks / Filters create and edit user extensions from the
  web UI (the form writes valid YAML); a raw YAML editor brings older or
  unrecognised files up to date. Endpoints: `/api/actions/save`,
  `/api/hooks/save`, `/api/filters/save`, `/api/extensions/delete`,
  `/api/extensions/file`; all honour read-only. `/api/config` also returns
  `hook_events`, `app_actions`, `backend_actions`,
   `action_defs`/`hook_defs`/`filter_defs` (each with `source`, `api_version`,
   `status`) and `extension_api_version`.
- Auth: accounts are a `{username: password_hash}` map in `users.json`
  (`USERS_FILE`, owner-only `0600`, hashed via `werkzeug.security`). A non-empty
  `USERS` turns login on: `before_request` returns 401 for `/api/*` without a
  signed session, while `/`, `/static/*` and
  `/api/{session,login,logout,setup}` stay public. The UI shows a first-run
  signup form when the store is empty (`/api/session` → `setup_required`), else a
  sign-in form, and offers Sign out and Change password. Routes: `GET
  /api/session`, `POST /api/setup` (only while empty), `POST /api/login`,
  `POST /api/logout`, `POST /api/password`. Account admin is CLI-only
  (`--create-user`/`--list-users`); there is no users tab in the UI.
- `app/VERSION`, `app/CHANGES` (per-version "what's new" notes shown once per
  installed version) and `CHANGELOG.md` (Keep a Changelog); `README.md` /
  `TUTORIAL.md` and `docs/` (`actions-and-hooks.md`, `filters.md`, `tags.md`,
  `dataset.md`, `install.md`) are user-facing docs.

## Cross-file invariants
- Built-in actions are the `app_*` set in `APP_ACTIONS` (`app/app.py`) and are
  implemented in `app/static/app.js`. Adding/renaming one requires editing both.
  Server-side actions are named in `BACKEND_ACTION_NAMES` (only
  `backend_rescan_images`).
- Hook events are `HOOK_EVENTS` (`app/app.py`), fired via `runHook('on_...')` in
  `app/static/app.js`, and documented in `app/hooks/example.yaml` plus
  `docs/actions-and-hooks.md` — keep all in sync.
- The extension YAML format is versioned by `EXTENSION_API_VERSION`
  (`app/app.py`); bump it when the action/hook/filter file format changes. The UI
  compares a file's `api_version:` against it.
- Read-only is enforced server-side (label, tag and extension writes return
  403), not only in the UI.

## Tests
- `tests/test_app.py` monkeypatches the module-level path constants above
  (shipped, `USER_*`, and the `*_FILE` state files) and resets `STATE`; keep
  those names module-level so tests can patch them. `clean_state` also patches
  `USERS_FILE` and resets `USERS = {}`.
- Fixtures create real JPEGs (Pillow) in `tmp_path`; tests never touch the repo's
  own `app/actions/`, `shortcuts.txt`, `.recent_data_yamls.json`,
  `.settings.json`, `.view_state.json` or `users.json`.

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

- Versioning (`app/VERSION`): update the major version when the public interface
  changes; update the minor version for minor changes. Add a matching
  `CHANGELOG.md` entry (and, when user-facing, an `app/CHANGES` note).

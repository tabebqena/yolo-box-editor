# AGENTS.md

## Project
Flask app for labelling images in YOLO format. The shipped code lives in `app/`:
`app/app.py` is now just the CLI entrypoint (flag parsing, user folder, session
secret key, then it runs the Flask app) and the implementation lives in the
plain `app/ybe/` package — `server.py` holds the Flask app object and all
routes, the rest are the reusable pieces (`config`, `state`, `parsing`, `auth`,
`dataset`, `extensions`, …). The UI is plain `app/templates/index.html` +
`app/static/style.css` + classic-script modules under `app/static/js/` (`core`,
`canvas`, `navigation`, `extensions`, `shortcuts`, `images`, `editing`,
`appearance`, `help`, `events`), finished by the `app/static/app.js` entry point;
small reusable DOM/modal helpers live in `js/core.js`. The built-in help ships as
HTML fragments under `app/static/help/` (`beginner`, `intermediate`, `expert`,
`howto`), opened with **F1** / the top-panel **?** button. **No build step**, and
the modules share one global scope, so the load order in `index.html` and
`tests/js/helpers/app.js` must stay in sync. No
database. The `data.yaml` reader is hand-rolled — no PyYAML at
runtime. User files live in `YBX_HOME` (below). The installer (`ybx.py`, started
by the thin `ybx.sh` bootstrap) copies `app/` wholesale, so `app/ybe/`,
`app/launcher.py`, `app/static/js/` and `app/static/help/` ship automatically.

## Commands
- Run: `python app/app.py --data /path/to/data.yaml` (optional `--readonly` to
  block writes, `--debug` for verbose browser-console logging, `--home` for a
  custom user folder; `--host`/`--port`, default `127.0.0.1:5000`). Other flags:
  `--no-resume` (open Settings instead of the last dataset), `--keep-pipe` and
  `--keep-filter-pipes` (keep scratch pipe files), `--no-update-check`,
  `--log-file`, `--no-reload`, `--flask-debug` (enable the Werkzeug interactive
  debugger + auto-reloader; off by default — development only), `--allow-root`
  (running as root is refused by default; this overrides for, e.g., containers).
  Auth admin commands (run, print and exit):
  `--create-user NAME` (prompts for the password with `getpass`, no echo) and
  `--list-users`. Flask's interactive debugger and auto-reloader stay off unless
  `--flask-debug` is passed; `--debug` only affects browser-console logging.
- Install/update/remove: the self-contained Python installer `ybx.py`
  (`install` / `upgrade` / `update` / `version` / `check-update` / `uninstall`);
  e.g. `./ybx.sh install --from .` or `python3 ybx.py install --from .`. It
  replaces only `<dir>/app/` atomically, refreshes `<dir>/ybx.py`, and leaves
  user files and `.venv` alone. It downloads with `urllib` (never curl) and is
  stdlib-only. `ybx.sh` (Unix) and `ybx.ps1` (Windows) are thin bootstraps that
  find Python and run `ybx.py`. `app/launcher.sh.in` and `app/launcher.cmd.in`
  are the thin Unix/Windows `ybe` shims that execute the Python launcher.
  (Replaces the old `install.sh`.)
- Python tests (from repo root): `python -m pytest -q` (~340 tests); single test
  `python -m pytest tests/test_app.py::test_name -q`. `pytest.ini` puts `app/`
  on `pythonpath`.
- JavaScript tests: `npm ci` then `npm run test:js` (Node's `node --test` +
  jsdom; Node >= 20). The suite lives in `tests/js/`. `package.json` and
  `package-lock.json` are committed; `/node_modules/` is gitignored. The release
  workflow runs this suite before creating a tag.
- No lint / format / typecheck config exists.
- Python tests import `PIL` (Pillow) but `app/requirements.txt` lists only
  `Flask`. Install Pillow (`pip install pillow`) or collection fails immediately.

## Layout / entrypoints
- `app/app.py` — the command-line entrypoint only: parses flags, resolves
  `YBX_HOME`, loads/creates the session secret key, seeds the default admin, then
  runs the Flask app from `ybe.server`. It also re-exports every helper the tests
  and embedders import (`from app import ...`), so those names stay available
  here even though their code lives in `ybe`.
- `app/launcher.py` — the `ybe` command's entry point: puts `app/` on
  `sys.path` and calls `ybe.launcher.main`. The installed `yolo-box-editor` /
  `ybe` command is only a three-line shim (rendered with `@DIR@`/`@VENV@` by the
  installer): `app/launcher.sh.in` on Unix (`exec`s the venv Python) and
  `app/launcher.cmd.in` on Windows. The installer picks the shim, writes it to
  the OS bin dir and creates the `ybe` alias (symlink on Unix, copy of the
  `.cmd` on Windows).
- `ybx.py` (repo root) — the self-contained installer/updater (stdlib only):
  `urllib` downloads, `tarfile` extraction, atomic `app/` swap, venv setup,
  self-copy to `<dir>/ybx.py` and launcher generation. `ybx.sh` / `ybx.ps1` are
  thin bootstraps that locate Python and run `ybx.py` (a sibling copy, else one
  fetched with `urllib`). The installer files stay outside `app/` so an update
  can replace the app while the installer keeps running.
- `app/ybe/` — the reusable package. Modules read shared values as
  `config.NAME` / `state.NAME` (never `from ybe.config import NAME`) so
  monkeypatching the owning module reaches every caller.
  - `config.py` — `BASE_DIR` (the shipped `app/` folder), `YBX_HOME` (the user
    folder), `configure_home`/`ensure_user_dirs`, the catalogs
    (`APP_ACTIONS`, `HOOK_EVENTS`, placeholders, `EXTENSION_API_VERSION`,
    timeouts, `MAX_RECENT`), and path constants: shipped `ACTIONS_DIR`,
    `HOOKS_DIR`, `FILTERS_DIR`, `APP_SCRIPT_DIR`, `SHORTCUTS_FILE`,
    `VERSION_FILE`, `CHANGES_FILE`; user `USER_ACTIONS_DIR`, `USER_HOOKS_DIR`,
    `USER_FILTERS_DIR`, `USER_SCRIPT_DIR`, `USER_SHORTCUTS_FILE`; state files
    `RECENT_FILE`, `VIEW_FILE`, `SETTINGS_FILE`, `CONFIG_FILE`,
    `UPDATE_CHECK_FILE`, `USERS_FILE` (the login accounts), `SECRET_KEY_FILE`
    (the session-signing key); and `FILTER_PIPES_DIR` (temp scratch).
  - `state.py` — the live containers: `STATE` (in-memory dataset state),
    `USERS` (`{username: password_hash}`, loaded from `USERS_FILE` at startup;
    a non-empty map turns login on), `EXECUTIONS`, `CLIENTS` + locks.
  - `server.py` — the Flask `app` object and every HTTP route (auth gate,
    config/settings, dataset/split/filter, actions and extension authoring,
    image and annotations).
  - `parsing.py` — pure text/YAML/shortcut helpers (no globals).
  - `dataset.py` — `data.yaml` loading, split/class scanning, label and tag paths.
  - `tags.py` — `tags.yaml` and the per-image tag files.
  - `filters.py` — the filter-chain contract and execution.
  - `extensions.py` — action/hook/filter YAML parse, validate, load and author.
  - `shortcuts.py`, `pipes.py` — the shortcut list and `{PIPE_PATH}` scratch files.
  - `userconfig.py` — `config.json` (recent datasets, view, settings, disabled
    extensions).
  - `commands.py` — the action queue, backend actions and shell command runner.
  - `auth.py` — the account store (`users.json`) and password hashing.
  - `update.py` — the GitHub version check and cached status.
  - `logging_setup.py` — `setup_logging` and the presence access-log filter.
  - `secret_key.py` — the persistent, owner-only session-signing key.
  - `launcher.py` — the Python `ybe` commands: start/stop/restart/status/logs
    (pid file + log in `YBX_HOME`, with stale/reused-PID detection via
    `procutil`). version/check-update/update/upgrade/uninstall delegate to
    `<YBX_HOME>/ybx.py`. Kept OS-neutral (no GNU-only shell tools) so the Unix
    and Windows shims share it.
  - `procutil.py` — the only OS-branching process code: pid liveness, reading a
    process command line, detaching a background server and stopping it, with a
    Linux (`/proc`) / macOS (`ps -ww`) / Windows (`OpenProcess`, PowerShell CIM,
    `DETACHED_PROCESS`, `taskkill`) implementation of each.
  There is deliberately no `SCRIPTS_DIR` symbol: scripts are reached relatively
  (`scripts/…`, since cwd is the home) or as `{APP_DIR}/scripts/…`.
- Frontend: `app/static/app.js` is the entry point only (login/account,
  `startApp`, `boot`, final event wiring). Everything else lives in
  `app/static/js/` as classic scripts loaded by `index.html` in dependency
  order: `core`, `canvas`, `navigation`, `extensions`, `shortcuts`, `images`,
  `editing`, `appearance`, `help`, `events`. They share one global lexical scope,
  so top-level `let`/`const`/functions are visible across files and the order in
  `index.html` and `tests/js/helpers/app.js` must match. `js/events.js` owns
  `ESCAPE_CLOSERS` (it references the overlay closers defined in earlier
  modules). `js/core.js` holds the shared DOM/modal helpers and mutable state.
  `js/help.js` owns the help modal (`openHelp`/`closeHelp`/`selectHelpTab`): it
  lazy-loads and caches the `app/static/help/*.html` fragments per tab.
- `YBX_HOME` resolution: `--home <dir>` > `$YBX_HOME` > the parent of `app.py`.
  The launcher (`ybe.launcher.resolve_home`) resolves it the same way (from the
  parent of the shipped `app/`), so a clone and an install behave the same; the
  folders are created at startup and the path is logged (`[ybe] user dir: …`).
- Extension files ship under `app/` and live (yours) under `YBX_HOME`, same
  names. The user copy is read after the shipped one and wins on a name clash;
  there is no `.a` variant:
  - `actions/*.yaml` — one action per file (`steps`, optional `after_success`,
    optional `name`).
  - `hooks/on_<event>.yaml` — event taken from the filename, else `event_name:`;
    `active: false` skips it.
  - Filters:
    - Contract: `python <filter.py> <data.yaml> <split> <in_pipe> <out_pipe>`; input holds the active split's absolute paths, output feeds the next filter (`run_filter_chain`). Runs with `cwd=YBX_HOME`.
    - UI: Filters button opens a modal with up to 8 stacked selects, run top-to-bottom (`app/static/js/`).
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
  (`USERS_FILE`, owner-only `0600`, hashed via `werkzeug.security`). `main()`
  calls `ensure_default_admin()`, which seeds `admin`/`admin`
  (`DEFAULT_ADMIN_USER`/`DEFAULT_ADMIN_PASSWORD`) when the store is empty, so a
  fresh install is usable with no setup. A non-empty `USERS` turns login on:
  `before_request` returns 401 for `/api/*` without a signed session, while `/`,
  `/static/*` and `/api/{session,login,logout}` stay public. The UI shows a
  sign-in form; Sign out and Change password live in **Settings → Account**
  (that tab appears only when login is enabled). Routes: `GET
  /api/session`, `POST /api/login`, `POST /api/logout`, `POST /api/password`.
  Account admin is CLI-only (`--create-user`/`--list-users`); there is no users
  tab in the UI. The session cookie is signed with `SECRET_KEY_FILE`
  (`secret_key.py`): a random 256-bit key written `0600` on first run and reused
  so sign-in survives restarts and updates (delete the file to invalidate every
  session).
- `app/VERSION`, `app/CHANGES` (per-version "what's new" notes shown once per
  installed version) and `CHANGELOG.md` (Keep a Changelog); `README.md`,
  `TUTORIAL.md` (the 3-level tutorial) and `docs/` (`actions-and-hooks.md`,
  `filters.md`, `tags.md`, `dataset.md`, `install.md`, `howto.md`) are
  user-facing docs.

## Cross-file invariants
- Built-in actions are the `app_*` set in `APP_ACTIONS` (`app/ybe/config.py`) and
  are implemented across the frontend modules (`app/static/js/`; the
  `app_*` handler map is `APP_SHORTCUT_HANDLERS` in `js/events.js`).
  Adding/renaming one requires editing both the catalog and the frontend.
  Server-side actions are named in `BACKEND_ACTION_NAMES` (only
  `backend_rescan_images`).
- Hook events are `HOOK_EVENTS` (`app/ybe/config.py`), fired via
  `runHook('on_...')` in `app/static/js/editing.js`, and documented in
  `app/hooks/example.yaml` plus `docs/actions-and-hooks.md` — keep all in sync.
- The built-in help is opened by the `app_help` action (shipped binding `F1`) and
  the top-panel **?** button. Its tabs are declared in three places that must
  stay in sync: the `.help-tab` buttons in `index.html`, `HELP_TABS` in
  `js/help.js`, and the fragments under `app/static/help/`.
- The extension YAML format is versioned by `EXTENSION_API_VERSION`
  (`app/ybe/config.py`); bump it when the action/hook/filter file format changes.
  The UI compares a file's `api_version:` against it.
- Read-only is enforced server-side (label, tag and extension writes return
  403), not only in the UI.

## Tests
- `tests/test_app.py` imports `app` and monkeypatches the path constants on
  `ybe.config` (shipped, `USER_*`, and the `*_FILE` state files), and resets
  `ybe.state.STATE`; keep those names module-level so tests can patch them.
  `clean_state` also patches `ybe.config.USERS_FILE` and resets
  `ybe.state.USERS = {}`. Direct calls to helper functions go through the
  `app` module (e.g. `ybe.load_filters()`), which re-exports them.
- Fixtures create real JPEGs (Pillow) in `tmp_path`; tests never touch the repo's
  own `app/actions/`, `shortcuts.txt`, `.recent_data_yamls.json`,
  `.settings.json`, `.view_state.json` or `users.json`.
- `tests/test_launcher.py` and `tests/test_installer.py` cover the Python
  launcher/installer: they spawn real child processes against a sleeping stub
  `app.py` (never Flask) and exercise stale-PID detection plus the offline
  install/uninstall paths with the venv and network mocked.
- `tests/js/*.test.js` is the frontend suite; add a file there (it is picked up
  automatically). `tests/js/helpers/app.js` loads `app/templates/index.html`
  into jsdom, stubs `fetch`/canvas/`requestAnimationFrame`/`confirm`, runs the
  `app/static/js/*.js` modules plus the `app.js` entry point — concatenated in
  the same order as `index.html` — in the window's vm context (without the
  trailing `boot();`), and injects `window.__ybe` (state get/set + the callable
  API). jsdom has no layout, so canvas drawing/layout is asserted through state
  and DOM, not pixels. Keep new reusable helper functions in
  `app/static/js/core.js` (they are exposed on `window` and covered in
  `tests/js/helpers.test.js`).

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

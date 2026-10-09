# AGENTS.md

## Project
Flask app for labelling images in YOLO format. The shipped code lives in `app/`:
`app/app.py` is now just the CLI entrypoint (flag parsing, user folder, session
secret key, then it runs the Flask app) and the implementation lives in the
plain `app/ybe/` package — `server.py` holds the Flask app object and all
routes, the rest are the reusable pieces (`config`, `state`, `parsing`, `auth`,
`dataset`, `extensions`, `widgets`, `packages`, …). The UI is plain
`app/templates/index.html` + `app/static/style.css` + classic-script modules
under `app/static/js/` (`core`, `api`, `canvas`, `navigation`, `extensions`,
`shortcuts`, `images`, `editing`, `appearance`, `widgets`, `plugin_api`,
`packages`, `help`, `events`), finished by the `app/static/app.js` entry point;
small reusable DOM/modal helpers live in `js/core.js`. An extension package
(`app/extensions/<id>/`) may bundle actions/hooks/filters/widgets, an optional
**shipped backend plugin** (`backend.py`: capabilities + HTTP routes), declared
`app_actions:`, a `permissions.yaml`, a **per-extension Python environment**
(`python:`/`requirements:`), self-contained tests (`tests/`), and an optional
**sandboxed UI panel** (an opaque-origin iframe whose only link to the app is the
async `YBE` bridge). Shipped examples: `app/extensions/example/` (a plain
package), `app/extensions/tags/` (the built-in Tags feature, moved out of core)
and `app/extensions/annotate/` (a sophisticated, `active: false` example: model
run, separate label folder, per-extension venv, canvas overlays). The built-in
help ships as
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
  Login accounts are managed by the launcher instead (`ybe users`; see below), not
  by an `app.py` flag. Flask's interactive debugger and auto-reloader stay off
  unless `--flask-debug` is passed; `--debug` only affects browser-console
  logging.
- Install/update/remove: the self-contained Python installer `ybx.py`
  (`install` / `upgrade` / `update` / `version` / `check-update` / `uninstall`);
  e.g. `./ybx.sh install --from .` or `python3 ybx.py install --from .`. It
  replaces only `<dir>/app/` atomically, refreshes `<dir>/ybx.py`, and leaves
  user files and `.venv` alone. It downloads with `urllib` (never curl) and is
  stdlib-only. `ybx.sh` (Unix) and `ybx.ps1` (Windows) are thin bootstraps that
  find Python and run `ybx.py`. `app/launcher.sh.in` and `app/launcher.cmd.in`
  are the thin Unix/Windows `ybe` shims that execute the Python launcher.
  (Replaces the old `install.sh`.)
- Python tests (from repo root): `python -m pytest -q` (~417 tests); single test
  `python -m pytest tests/test_app.py::test_name -q`. `pytest.ini` puts `app/`
  on `pythonpath`. A shipped package's own tests live next to it under
  `app/extensions/<id>/tests/` (self-contained; run one package with
  `python -m pytest app/extensions/<id> -q`).
- Extension CLI (from the launcher): `ybe extensions` (list), `ybe
  install-extension <path> [--yes] [--force] [--env] [--no-env]`, `ybe
  remove-extension <id>`, `ybe extension-env <id> [--python CMD] [--status]`
  (build/inspect a package's Python environment).
- JavaScript tests: `npm ci` then `npm run test:js` (Node's `node --test` +
  jsdom; Node >= 20). The suite lives in `tests/js/`. `package.json` and
  `package-lock.json` are committed; `/node_modules/` is gitignored. The release
  workflow runs this suite before creating a tag.
- No lint / format / typecheck config exists.
- Python tests import `PIL` (Pillow) but `app/requirements.txt` lists only
  `Flask`. Install Pillow (`pip install pillow`) or collection fails immediately.

## Layout / entrypoints
- `app/app.py` — the command-line entrypoint only: parses flags, resolves
  `YBX_HOME`, loads/creates the session secret key and the login store, then
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
    (`APP_ACTIONS`, `HOOK_EVENTS`, placeholders, `EXTENSION_API_VERSION` = 6,
    `PLUGIN_API_VERSION` = 5, timeouts, `MAX_RECENT`), and path constants:
    shipped `ACTIONS_DIR`, `HOOKS_DIR`, `FILTERS_DIR`, `WIDGETS_DIR`,
    `EXTENSIONS_DIR`, `APP_SCRIPT_DIR`, `SHORTCUTS_FILE`,
    `VERSION_FILE`, `CHANGES_FILE`; user `USER_ACTIONS_DIR`, `USER_HOOKS_DIR`,
    `USER_FILTERS_DIR`, `USER_WIDGETS_DIR`, `USER_EXTENSIONS_DIR`,
    `USER_SCRIPT_DIR`, `USER_SHORTCUTS_FILE`, `EXTENSION_ENVS_DIR` (per-package
    venvs); state files
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
  - `dataset.py` — `data.yaml` loading, split/class scanning, label paths.
  - `filters.py` — the filter-chain contract and execution.
  - `extensions.py` — action/hook/filter/widget YAML parse, validate, load and
    author (the loaders iterate `packages.extension_sources(kind)` so active
    package subfolders are read too, flat files winning per source).
  - `widgets.py` — custom-widget YAML parse/validate/load and
    `sanitize_widget_values` (control values become `{WIDGET_<ID>}` placeholders).
  - `packages.py` — extension-package discovery: `load_packages`, the
    `extension.yaml` parser (`settings:` reuse the widget parser; `events:`;
    `ui:`; `backend:`; `app_actions:`; `python:`/`requirements:`/
    `requirements_file:`), `extension_sources`, `package_script_path` /
    `package_backend_path` (realpath guards) and `plugin_api_status`.
  - `envs.py` — per-extension Python environments: `resolve`/`requirements_for`/
    `setup` (venv/current/path) and `placeholder_values` (the `{EXT_*}` values).
  - `permissions.py` — the `permissions.yaml` model, the YBE capability/
    method→permission maps, and the honesty/coverage check.
  - `compat.py` — the declared support registry for the extension/plugin API
    versions (`support_status`, `version_error`, `support_table`).
  - `plugins.py` — the shipped-only backend-plugin loader: `register(ctx)`
    capabilities, `extension_routes`, runtime `enable`/`disable`/`dispatch`.
  - `extension_flags.py` — the per-user `extensions.json` enable/disable overrides.
  - `shortcuts.py`, `pipes.py` — the shortcut list and `{PIPE_PATH}` scratch files.
  - `userconfig.py` — `config.json` (recent datasets, view, settings, disabled
    extensions).
  - `commands.py` — the action queue, backend actions and shell command runner.
  - `auth.py` — the account store (`users.json`) and password hashing, plus the
    `create_user`/`update_user`/`delete_user` used by `ybe users`.
  - `update.py` — the GitHub version check and cached status.
  - `logging_setup.py` — `setup_logging` and the presence access-log filter.
  - `secret_key.py` — the persistent, owner-only session-signing key.
  - `launcher.py` — the Python `ybe` commands: start/stop/restart/status/logs
    (pid file + log in `YBX_HOME`, with stale/reused-PID detection via
    `procutil`), `users` (list/`--create`/`--update`/`--delete` login accounts,
    editing `users.json` directly so it works while the server runs), and the
    extension commands `extensions`/`install-extension`/`remove-extension`/
    `extension-env` (the last builds a package's venv or prints its status).
    version/check-update/update/upgrade/uninstall delegate to
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
  order: `core`, `api`, `canvas`, `navigation`, `extensions`, `shortcuts`,
  `images`, `editing`, `appearance`, `widgets`, `plugin_api`, `packages`,
  `help`, `events`. They share one global lexical scope,
  so top-level `let`/`const`/functions are visible across files and the order in
  `index.html` and `tests/js/helpers/app.js` must match. `js/events.js` owns
  `ESCAPE_CLOSERS` (it references the overlay closers defined in earlier
  modules). `js/core.js` holds the shared DOM/modal helpers and mutable state.
  `js/appearance.js` owns the dock registry (`WIDGETS`, `registerWidget`,
  `createWidgetFrame`, `unregisterWidget`); `js/widgets.js` builds custom
  widgets and their Layout sections. `js/plugin_api.js` owns the sandboxed-panel
  bridge (`PANELS`, the `YBE` capability table, `buildPanelSrcdoc` and the
  injected iframe stub); `js/packages.js` renders the Settings → Extensions tab
  and mounts/tears down panels. `js/help.js` owns the help modal
  (`openHelp`/`closeHelp`/`selectHelpTab`): it
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
  - `widgets/<name>.yaml` — a custom widget: `title` + `controls`
    (button/select/checkbox/input); a button runs an action (by name) or inline
    `steps`/`after_success`, and the other controls' values become
    `{WIDGET_<ID>}` placeholders. Shown/placed from the Layout tab.
  - `scripts/*.py` — helpers named by action `steps`; the app never scans them.
    Reach them explicitly with `{USER_SCRIPT_DIR}/…` (yours) or
    `{APP_SCRIPT_DIR}/…` (shipped), or relatively as `scripts/…` (cwd is
    `YBX_HOME`). Shipped helpers: `class_filter.py`, `example.py`,
    `example_filter.py`, `tag_filter.py`, `tag_image.py`.
  - `shortcuts.txt` — `ACTION_NAME <KEY> label`.
- Extension **packages** (`app/extensions/<id>/`, user `<home>/extensions/<id>/`)
  are an additive layer over the flat folders above: an `extension.yaml`
  manifest plus optional `actions/`, `hooks/`, `filters/`, `widgets/`,
  `scripts/`, `backend.py`, `panel.js`, `permissions.yaml` and `tests/`. The
  manifest's `settings:` block becomes a Settings → Extensions subtab (same
  control format as a widget), `ui:` declares a sandboxed UI panel
  (`api_version`/`title`/`script`/`location`/`height`), `events:` lists extra
  event names, `app_actions:` declares extension app actions (`ext.<id>.<name>`
  with an optional `capability:` fallback), `backend:` names a shipped backend
  plugin, and `python:`/`requirements:`/`requirements_file:` declare a
  per-extension Python environment. Flat files always win over a package file of
  the same name/source. `active: false` lists the package but loads nothing (a
  per-user override in `<home>/extensions.json` wins). A package's own tests live
  in its `tests/`.
- Tags: the built-in feature now lives in the `app/extensions/tags/` package
  (`active: false` by default; backend `backend.py` + panel). `tags.yaml` beside
  `data.yaml` is the available-tag list; an image's own tags live in a sibling
  tag file and are written with its labels on save (not instantly). The folder is
  overridable per dataset (`POST /api/extension/tags/dir`).
- Commands and filters run with `cwd=YBX_HOME` (logged per run) and receive
  `YBE_HOME`, `YBE_APP_DIR`, `YBE_APP_SCRIPT_DIR`, `YBE_USER_SCRIPT_DIR`;
  placeholders include `{APP_DIR}`, `{HOME_DIR}`, `{APP_SCRIPT_DIR}`,
  `{USER_SCRIPT_DIR}`, `{PYTHON}`, `{PIPE_PATH}` and, for a package's own
  steps, `{EXT_DIR}`, `{EXT_PYTHON}`, `{EXT_ENV_DIR}` (filters add `{SPLIT}`,
  `{INPUT_PIPE}`, `{OUTPUT_PIPE}`).
- Settings → Actions / Hooks / Filters create and edit user extensions from the
  web UI (the form writes valid YAML); a raw YAML editor brings older or
  unrecognised files up to date. Endpoints: `/api/actions/save`,
  `/api/hooks/save`, `/api/filters/save`, `/api/extensions/delete`,
  `/api/extensions/file`; all honour read-only. `/api/config` also returns
  `hook_events`, `app_actions`, `backend_actions`,
   `action_defs`/`hook_defs`/`filter_defs`/`widget_defs` (each with `source`,
   `api_version`, `status`; the defs also carry `package`),
   `widget_errors`, `extension_packages` (id/name/version/source/active/parts/
   settings/events/`ui`/`environment`) + `package_errors`, `extension_api_version`,
   `plugin_api_version`, `extension_app_actions`, `plugin_permissions` and
   `plugin_permission_map`. Settings → Layout shows/places each custom widget;
   Settings → Extensions renders one subtab per package (with a Python-env
   status + **Set up environment** button). Run routes:
   `POST /api/widgets/run` and `POST /api/extensions/run` execute a
   button/step through the action engine with `{WIDGET_<ID>}` values;
   `GET /api/extensions/script?package=<id>` serves a panel script (active
   packages only, path-guarded) to the host, which inlines it into the sandbox
   iframe (the iframe itself has no network). Other extension routes:
   `POST /api/extensions/active` (enable/disable live), `POST
   /api/extensions/env` (build the Python environment), `POST
   /api/extensions/call` (headless capability), and the startup catch-all
   `/api/<path:subpath>` that dispatches a package's declared `extension_routes`.
- Auth: login is **opt-in**. Accounts are a `{username: password_hash}` map in
  `users.json` (`USERS_FILE`, owner-only `0600`, hashed via
  `werkzeug.security`). An empty/absent store means no login (the local default);
  any entry turns it on. `main()` only loads the store (`load_users()`); there is
  no seeded/default account. A non-empty `USERS` makes `before_request` return
  401 for `/api/*` without a signed session, while `/`, `/static/*` and
  `/api/{session,login,logout}` stay public. The UI shows a sign-in form; Sign out
  and Change password live in **Settings → Account** (that tab appears only when
  login is enabled). Routes: `GET /api/session`, `POST /api/login`,
  `POST /api/logout`, `POST /api/password`. Account admin is CLI-only
  (`ybe users`; see the launcher); there is no users tab in the UI. The session
  cookie is signed with `SECRET_KEY_FILE` (`secret_key.py`): a random 256-bit key
  written `0600` on first run and reused so sign-in survives restarts and updates
  (delete the file to invalidate every session).
- `app/VERSION`, `app/CHANGES` (per-version "what's new" notes shown once per
  installed version) and `CHANGELOG.md` (Keep a Changelog); `README.md`,
  `TUTORIAL.md` (the 3-level tutorial) and `docs/` (`actions-and-hooks.md`,
  `filters.md`, `tags.md`, `dataset.md`, `install.md`, `howto.md`,
  `widgets.md`, `extensions.md`, `extensions-ui.md`, `extension-actions.md`,
  `building-extensions.md`) are user-facing docs.

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
  (`app/ybe/config.py`); bump it when the action/hook/filter/widget/package
  file format changes (currently 6; the support window is the last 3 versions,
  declared in `compat.py`). The UI compares a file's `api_version:` against it.
  The sandboxed-panel `YBE` API is versioned separately by `PLUGIN_API_VERSION`
  (currently 5; a package declares `ui.api_version:`); bump it when a `YBE`
  method/event's meaning changes or a method is added — the shipped panels'
  `ui.api_version:` must then be bumped to match.
- Backend plugins (`backend.py`) are **trusted, shipped-only** code: `plugins.py`
  loads one only for a `source == "shipped"` package. Routes are declared in an
  `extension_routes` tuple (never `@app.route`) and dispatched by the startup
  catch-all, so enabling/disabling is live. Panel overlays
  (`YBE.callbacks.drawBox`/`setDrawnBoxes`/`clearDrawnBoxes`/`setDrawnBoxesVisible`)
  are render-only (never saved); saving is `setBoxes`/`addBox` + `save`.
- Adding/renaming an extension kind or a UI surface touches several places that
  must stay in sync: the shipped/user dirs in `config.py` (+`configure_home` and
  `ensure_user_dirs`), the loader in `extensions.py`/`widgets.py`, the
  `/api/config` payload, the Settings tab markup + `js/navigation.js` +
  `js/events.js` wiring, and the JS load order in `index.html` and
  `tests/js/helpers/app.js`. Custom widgets and panels register into the same
  `WIDGETS` dock registry (`js/appearance.js`); panels additionally emit editor
  events via `emitUiEvent` in `js/plugin_api.js`.
- Read-only is enforced server-side (label, tag and extension writes return
  403), not only in the UI. `YBE` mutators also refuse in read-only mode; the
  sandbox is containment for untrusted panel code, not a substitute for the
  server-side check.

## Tests
- `tests/test_app.py` imports `app` and monkeypatches the path constants on
  `ybe.config` (shipped, `USER_*` — including `WIDGETS_DIR`/`USER_WIDGETS_DIR`
  and `EXTENSIONS_DIR`/`USER_EXTENSIONS_DIR` — and the `*_FILE` state files),
  and resets `ybe.state.STATE`; keep those names module-level so tests can patch
  them. `clean_state` also patches `ybe.config.USERS_FILE`,
  `ybe.config.EXTENSION_ENVS_DIR` and resets `ybe.state.USERS = {}`. Direct calls
  to helper functions go through the `app` module (e.g. `ybe.load_filters()`),
  which re-exports them.
- A shipped package's own tests live next to it (`app/extensions/<id>/tests/`,
  self-contained, picked up by `python -m pytest -q`): `tags/tests/test_tags.py`,
  `annotate/tests/test_annotate.py`. Framework tests stay in
  `tests/test_plugins.py`.
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

# Changelog

All notable changes to **yolo-box-editor** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [7.21.0] - 2026-10-08

### Added

- **Isolate the selected box** (`app_isolate_box`, default key `I`): hide every
  box except the selected one to inspect it among many; hidden boxes ignore the
  mouse. Press `I` again — or deselect — to show them all. Rebindable in
  **Settings → Shortcuts** and remembered per browser.

### Fixed

- The README keyboard cheat sheet now lists `F1` (open help) and `,` (toggle box
  details), which were missing.

## [7.20.0] - 2026-10-08

### Changed

- **Login is now opt-in.** The app no longer ships a default `admin`/`admin`
  account, so a fresh install (and any install with an empty `users.json`) opens
  with no sign-in — the right default for a local, single-user setup. Register an
  account with `--create-user NAME` to require sign-in for a shared or LAN
  instance; delete `users.json` to turn it back off. This removes the previously
  seeded public default password.

### Removed

- The `ensure_default_admin()` seed and the `DEFAULT_ADMIN_USER` /
  `DEFAULT_ADMIN_PASSWORD` constants.

## [7.18.0] - 2026-10-07

### Added

- **Built-in help.** The app now ships a 3-level tutorial — **Beginner**
  (install, the screen, draw / move / resize / delete boxes and their shortcuts),
  **Intermediate** (layout, keyboard row editing, tags, filters, read-only) and
  **Expert** (your own actions, filters, hooks and shortcut rebinding) — plus a
  **How to?** section of task-focused recipes. Open it with **F1**, the new
  **?** button in the top panel, or the new `app_help` action (rebindable in
  `shortcuts.txt`). Content ships as HTML fragments under `app/static/help/`.
- New repo docs: [How to?](docs/howto.md), and [TUTORIAL.md](TUTORIAL.md) is now
  the three-level tutorial.

## [7.17.0] - 2026-10-07

### Changed

- **The app/ swap now retries transient file locks** (up to ~3s) instead of
  failing. This is mainly for Windows (and antivirus/indexers elsewhere) where a
  file can be briefly locked during an update; the whole `place_app()` rename and
  cleanup path now waits the lock out and reports clearly if it cannot.
- **The launcher and installer shims are POSIX `sh`** (`#!/bin/sh`) instead of
  bash, so install and run work on distributions without bash (e.g. Alpine);
  `ybx.sh` is now POSIX sh and the documented one-liner uses `sh -s --`.

### Documentation

- A **platform-support note** now says the app has so far been used on
  Debian-based Linux; macOS and other Linux distributions run the same code, and
  Windows support is brand new (it reuses the same Python core through Windows
  APIs). Feedback is welcome, and `ybe uninstall` undoes an install cleanly.

## [7.16.0] - 2026-10-07

### Added

- **Windows support.** `ybe` (and the installer) now work natively on Windows:
  the installer writes `yolo-box-editor.cmd` + `ybe.cmd` to
  `%LOCALAPPDATA%\yolo-box-editor\bin`, adds that folder to your user `PATH`,
  and installs to `%LOCALAPPDATA%\yolo-box-editor`. There is a PowerShell
  bootstrap, `ybx.ps1` (`irm .../ybx.ps1 -OutFile ybx.ps1; .\ybx.ps1 install`).
  Background start/stop/status and stale-PID detection use Windows APIs
  (`OpenProcess`, `DETACHED_PROCESS`, `taskkill`) behind the same
  `app/ybe/procutil.py` used on Linux/macOS, so all commands behave the same.
- The launcher and installer were refactored so the OS-specific process code
  lives in one place (`app/ybe/procutil.py`); the installer now stops a running
  server before swapping `app/` (important on Windows) and drives stop/status
  through the launcher instead of duplicating the logic.

## [7.15.0] - 2026-10-07

### Changed

- **The launcher (`ybe`) and installer are now implemented in Python.** The
  `ybe` command is still a tiny shell shim, but all of its logic — start, stop,
  restart, status, logs and the delegated version/update/uninstall commands —
  now lives in `app/ybe/launcher.py`, and the installer is a self-contained
  `ybx.py`. This removes the GNU-only shell tools (notably `sort -V`) that made
  some commands unreliable on macOS, so Linux and macOS now behave the same. A
  Windows `.cmd`/`.ps1` shim can reuse the same module.
- **Install and update downloads no longer shell out to curl.** The installer
  fetches the app archive with Python's `urllib`, so only Python 3 is required
  (the optional one-line bootstrap still uses curl to fetch the tiny shim).
- The `ybe` and installer CLI are unchanged (`ybe update`, `ybx.py install
  --from .`, `--latest`, `--commit`, `--purge`, …); only the implementation and
  the docs changed.

## [7.14.0] - 2026-10-07

### Fixed

- **`ybe status` (and `ybe stop` / upgrade / uninstall) no longer trusts a stale
  PID.** After a crash or reboot the launcher could leave `ybe.pid` behind; if
  the OS reused that PID for an unrelated process, `ybe status` reported the app
  as running and `stop` could signal the wrong process. The launcher now checks
  that the PID's command line actually references the app before treating it as
  running.

## [7.13.0] - 2026-10-05

### Changed

- **Dragging or drawing a box no longer redraws every other box.** The image and
  the untouched boxes are cached on an offscreen layer and blitted each frame,
  with only the active box repainted. This keeps the pointer fluid on images
  with hundreds of boxes; there are no behaviour changes.

## [7.12.0] - 2026-10-05

### Changed

- **Dragging a box no longer refreshes the side panel on every mouse move.** The
  canvas still tracks the box live; the box's row (coordinates, selection) is
  synced once when you release the mouse. This keeps dragging responsive on
  images with many boxes, at the cost of the coordinate inputs not ticking
  during the drag.

## [7.11.0] - 2026-10-05

### Added

- **A new action and shortcut for a minimal box view.** Press `,` (or bind
  `app_box_details`) to hide the resize anchors, the class-name label and the
  `x` / `/` corner buttons, leaving only the box outlines. Press it again to
  bring them back; the choice is remembered across reloads.

## [7.10.0] - 2026-10-05

### Added

- **A reload button beside the Split selector.** It re-scans the image folders
  and re-runs the active filter chain for the selected split, then keeps you on
  the same image. Handy when images or filter results changed on disk.

### Changed

- **Switching split now shows a spinner at the Split control** and temporarily
  blocks the selector and reload button. Changing split can re-run the filter
  chain, so the busy feedback makes it clear the list is still updating.

## [7.9.0] - 2026-10-04

### Added

- **Two new built-in filters, Has tag and Does not have tag.** They keep only
  the images whose tag file does (or does not) contain the chosen tag. The tag
  is picked from a dropdown filled from the dataset's `tags.yaml`, via the new
  dynamic option token `options: {DATASET_TAG_NAMES}`.
- **New filter placeholder `{TAGS_DIR}`** — the active split's tags folder, so a
  filter can honour a custom tags folder. The shipped tag filters use it;
  `app/scripts/tag_filter.py` backs them.
- **New action placeholder `{TAGS_DIR}`** — the current image's split tags
  folder, and `app/scripts/tag_image.py` gained `--tags-dir` so an action can
  write tags to a custom tags folder too.

### Fixed

- **`app/scripts/tag_image.py` no longer mangles paths that merely contain the
  substring `images`** (e.g. an `images_backup` folder). It now swaps only the
  last whole `images` path segment, exactly like the app, and honours the
  per-dataset custom tags folder.

## [7.8.0] - 2026-10-04

### Changed

- **Running an action or hook no longer shows automatic success feedback.**
  A successful run is silent and logged to the browser console; only a failure
  notifies you, with a toast carrying the reason. Previously a hook toasted
  "`<name>` succeeded" and a manual action opened the action-result modal.

## [7.7.0] - 2026-10-04

### Fixed

- **Creating or resizing a box no longer gets slow on images with many boxes.**
  Every mouse move during a drag redrew the canvas and re-synced the whole
  side-panel box list, so the work grew with the number of boxes and the pointer
  started ignoring drags. A move/resize now updates only the dragged box's row,
  and the hover cursor only checks the selected box's handles, so editing stays
  responsive regardless of how many boxes an image has.

## [7.6.0] - 2026-10-04

### Fixed

- **The app no longer gets heavy after browsing many images.** Each image is now
  decoded with `createImageBitmap` and drawn as a bitmap that is explicitly
  released when the next image loads, instead of relying on the browser's
  per-URL `<img>` decode cache, which kept growing the more images were viewed.
  This stops the memory creep (and the sluggish pointer/clicks) on long
  labelling sessions.

## [7.5.0] - 2026-10-04

### Added

- **Four built-in app actions for actions and hooks.** `app_select_next_box`,
  `app_select_prev_box`, `app_clear_tags` and `app_copy_labels_from_prev` can be
  listed in an action's or hook's `steps` / `after_success` (or bound to a key in
  `shortcuts.txt`). They run in the browser like the other `app_*` actions and do
  nothing in read-only mode.

## [7.4.0] - 2026-10-04

### Changed

- **Change password and Sign out moved out of the side panel's top bar.** They
  now live in a dedicated **Settings → Account** tab, which appears only when
  sign-in is enabled. This keeps the top bar focused on the app (settings,
  notifications, panel toggle).

## [7.3.0] - 2026-10-04

### Changed

- **Flask's interactive debugger and auto-reloader are now off by default.** They
  were enabled unconditionally, which meant that on an unhandled error anyone who
  could reach the app got the Werkzeug debug console — arbitrary code execution
  as the app's user. Development use now requires the new **`--flask-debug`**
  flag; `--no-reload` only applies with it. `--debug` is unchanged and still only
  controls verbose browser-console logging. Combining `--flask-debug` with a
  non-localhost `--host` logs a warning.

### Security

- The debug console is never bound by default any more, closing an
  easily-overlooked path to code execution (especially with `--host 0.0.0.0`).

## [7.2.0] - 2026-10-04

### Added

- **Root guard.** Starting the app as root now aborts with a clear message
  instead of continuing. Running as root makes every written file (`users.json`,
  `.secret_key`, labels, tags, logs) owned by root — and, because those files are
  stored `0600`, unreadable by the normal user — and runs the `debug=True`
  Werkzeug console with root privileges. Pass the new **`--allow-root`** flag to
  override, for setups (e.g. containers) where root is expected; a warning is
  logged when the override is used.

## [7.1.0] - 2026-10-04

### Changed

- **Sign-ins now survive a restart.** The Flask session-signing key is generated
  once and stored in `.secret_key` in the user folder (`0600`) instead of being
  random per process, so `ybe restart` / `ybe update` no longer sign everyone
  out. The file lives outside `app/`, so an app update keeps it; delete it to
  force a new key (which invalidates existing sessions).

## [7.0.0] - 2026-10-04

### Added

- **Login** backed by a persistent, multi-user account store. The app ships with
  a ready-to-use default account — **`admin` / `admin`** — created on first run,
  so `ybe start` is usable immediately with no setup. Change the password from
  the side panel (**Change password**; the current password is required) and use
  **Sign out** to end the session. Every `/api/*` call returns `401` until signed
  in. Accounts can also be managed from the command line with `--create-user
  NAME`, which **prompts for the password without echo** (so it never lands in
  the shell history or the process list), and `--list-users`.

  Accounts live in `users.json` in the user folder, stored as salted PBKDF2
  hashes (never plaintext) with owner-only (`0600`) permissions. New routes:
  `GET /api/session`, `POST /api/login`, `POST /api/logout`, `POST /api/password`;
  `/api/config` reports an `auth` object.

### Security

- The shipped default password `admin` is public and must be changed. The login
  is a **convenience gate, not strong security**: over plain `http://` the
  password is sent in the request body (cleartext). Use it only on localhost or a
  trusted network, or behind an HTTPS reverse proxy. The stored hashes protect
  the file; passwords are never passed on the command line.

## [6.9.0] - 2026-10-03

### Changed

- **The Create action / hook / filter forms now look like a small editor**: a
  titled header with a file badge (e.g. `action.yaml`), grouped **Details** /
  **Arguments** / **Steps** / **After success** sections, monospace command and
  argument fields, and a **sticky footer** with the Create / Clear buttons so
  they stay reachable in a long form.

## [6.8.0] - 2026-10-03

### Changed

- **Settings → Actions** and **Settings → Hooks** now use **Create** /
  **Existing** sub-tabs, matching the Filters tab, instead of one long panel.
  The sub-tab styling/behaviour is shared (`sub-tabs` / `sub-tab` / `sub-panel`).
- **The Settings dialog sizes to the active tab** — it hugs its content and only
  a tall tab is capped (`min(80vh, 620px)`) and scrolled, instead of filling the
  screen.

## [6.7.0] - 2026-10-03

### Added

- **Add / remove rows in the filter chain** (Settings → Filters → Active chain):
  a **+ Add filter** button appends a row (up to the 8-filter limit) and each row
  has a **×** to remove it (the last row stays, so there is always a slot).

### Changed

- **Applying a filter chain shows a spinner** on the Apply button and **closes
  the Settings dialog** when the chain has been applied. Clear behaves the same.

## [6.6.0] - 2026-10-03

### Changed

- **Settings → Filters** is split into three sub-tabs — **Active chain**,
  **Create** and **Library** — shown as a segmented control, instead of one long
  scrolling panel. The chain sub-tab states that up to **8** filters run top to
  bottom; the Create form and the existing-filters list now each get their own
  sub-tab.

## [6.5.0] - 2026-10-03

### Added

- **The last image is remembered across browsers.** The browser still keeps its
  fast local copy, but every change is now mirrored to the backend under
  `settings.ybe_last_image`, so opening the app in a different browser resumes at
  the same image (per dataset and split). The update/seen-update and
  tip-of-the-day memories are mirrored the same way.
- **One user config file.** `.recent_data_yamls.json`, `.view_state.json` and
  `.settings.json` are merged into a single `config.json` in the user folder
  (`{"recent": [...], "views": {...}, "settings": {...}}`, written atomically).
  It sits in `YBX_HOME`, outside `app/`, so app updates never touch it.

### Changed

- Existing installs migrate automatically on first start: the three legacy files
  are read, written into `config.json` and then removed. An unreadable
  `config.json` is left in place rather than overwritten, so it can be fixed by
  hand.

## [6.4.0] - 2026-10-03

### Added

- Disable an action or hook **for the loaded dataset only**, from Settings →
  Actions / Hooks, using the **Enabled for this dataset** checkbox. The
  extension file is never modified: the choice is remembered per `data.yaml`,
  the toolbar button disappears and the hook stops firing (a disabled action
  also cannot be run as an `action_<Name>` reference), and it can be re-enabled
  at any time. `POST /api/extensions/disabled` backs the toggle; `/api/config`
  reports an `enabled` flag per def, and `/api/actions/run` refuses a disabled
  name.

## [6.3.0] - 2026-10-02

### Added

- Two **before-leave event hooks**, `on_before_prev` and `on_before_next`,
  fired when leaving the current image with the previous / next navigation,
  **before** the unsaved-changes / auto-save handling. They appear in the
  Settings → Hooks event list. The existing `on_prev` / `on_next` hooks are
  unchanged and still fire just before the image is replaced.

## [6.1.0] - 2026-10-02

### Fixed

- The app no longer slows down after browsing many images. Each cache-busted
  image load now releases the previous decoded frame first, instead of retaining
  one decoded bitmap per viewed image until the tab is closed.

## [6.0.0] - 2026-10-02

### Added

- **Create actions, hooks and filters from the web UI** (Settings → Actions /
  Hooks, and a "Create a filter" section in Settings → Filters). The form writes
  valid YAML itself, so indentation, missing `:` and missing `-` mistakes cannot
  happen. Each command row has a **click-to-insert placeholder palette**
  (`{IMAGE_PATH}`, `{USER_SCRIPT_DIR}`, `{INPUT_PIPE}`, …) so their spelling need
  not be memorised. List and delete your own extensions next to the form.
- Extension YAML now carries an **`api_version`** key. A file whose version is
  missing or older than the UI is flagged **outdated** and can be opened in a
  **raw YAML editor** (comments and unknown keys are preserved); saving bumps
  `api_version` to the current value and, for a shipped file, writes a user
  override. A file **newer** than the app is blocked with a warning.

### Changed

- New endpoints `/api/actions/save`, `/api/hooks/save`, `/api/filters/save`,
  `/api/extensions/delete` and `/api/extensions/file` (read/write); `/api/config`
  now also returns `extension_api_version`, `placeholders`, `hook_events`,
  `app_actions`, `backend_actions` and `action_defs` / `hook_defs` / `filter_defs`
  (each with `source`, `api_version` and `status`). All extension writes honour
  read-only mode.
- Shipped filters declare `api_version: 1`. Files without it still load.

### Fixed

- Undo/Redo now cover the common canvas edits — drawing a box, moving it,
  resizing it and changing its class from the canvas picker. Those edits left the
  history empty, so the Undo button stayed disabled and the `Z` shortcut did
  nothing; auto-save was not involved.

## [5.0.0] - 2026-10-02

### Added

- `options` supports the dynamic token `{DATASET_CLASS_NAMES}`, expanded to the
  loaded dataset's class names, so an argument can be a class dropdown instead of
  free text; the app rejects a value outside `options`.
- Shipped **Contains class** and **Does not contain class** filters
  (`app/filters/contains_class.yaml`, `app/filters/not_contains_class.yaml`)
  backed by `app/scripts/class_filter.py`.

### Changed

- **Filters are now defined by YAML** (breaking): one `filters/*.yaml` file per
  filter instead of one Python script. A filter declares `name` (defaults to the
  file name), an optional `description`, an `active` on/off switch, an
  `arguments` list (`name`, `required`, `default`, `options`) and `steps` shell
  commands. The filter logic moves to helper scripts under `scripts/` (shipped
  helpers are `app/scripts/`). `app/filters/example.py` is replaced by a working
  `app/filters/example.yaml` backed by `app/scripts/example_filter.py`.
- Each step is run like an action step: the app substitutes and shell-quotes the
  shared placeholders plus `{DATA_YAML_PATH}`, `{DATASET_PATH}`, `{SPLIT}`,
  `{INPUT_PIPE}` and `{OUTPUT_PIPE}`; every declared argument is also usable in
  place as its upper-cased name (`threshold` -> `{THRESHOLD}`). There is no
  `after_success`. The new `{PYTHON}` placeholder is the interpreter running the
  app, so shipped filters run even when `python` is not on `PATH`.
- **Settings → Filters** now shows each filter's name and a trimmed description,
  and renders one input per argument (a dropdown when `options` is given).
  `active: false` filters are hidden. Argument names must be simple identifiers
  and must not shadow a built-in placeholder; a bad one drops the filter and the
  error is shown.
- `POST /api/filter` takes `{filters: [{name, arguments}, ...]}` (a list of
  names and `{filter: name}` are still accepted); the active chain — including
  argument values — is remembered per dataset. `GET /api/config` now returns a
  filter metadata catalog plus `filter_errors`.

### Removed

- Python-script filters (`filters/*.py`) and the old fixed
  `python <script> <data.yaml> <split> <in> <out>` contract; put the logic in a
  `scripts/` helper and call it from a YAML `steps` entry instead.

## [4.0.0] - 2026-10-02

### Changed

- The control panel (Tags, Boxes, Actions, Navigation, Save) now sits on the
  **left** by default. Change it in **Settings → Layout → Control panel side**.
- Saving an image now writes its labels and tags together: the backend writes
  the image's tag file and adds only new tag names to `tags.yaml` (no rewrite
  when nothing is new). Tag edits are written on save instead of instantly.
- Tag edits now take part in undo/redo (`Z` / `Y`), and the undo history is
  reset per image.
- `GET`/`POST /api/labels` is now `GET`/`POST /api/annotations`. `GET` returns
  `{"boxes": [...], "tags": [...]}`; `POST` still saves the boxes and tags.

### Removed

- The built-in `update_tags` action and the shipped `on_after_save` hook that
  ran it; tag persistence is handled by the save itself. `app_update_tags` is no
  longer a built-in app action. `on_after_save` remains a valid hook event for
  your own hooks.
- The `/api/tags` and `/api/tags.yaml` endpoints; per-image tags are read and
  written through `/api/annotations` (the dataset tag list is still
  `tags.yaml`, managed server-side).

## [3.6.0] - 2026-10-02

### Fixed

- The tag bar now reads `tags.yaml` as a plain list — one tag per line, each
  prefixed by `- ` (the format written by `dataset_autotag.py`) — so every tag
  is shown instead of only those under a nested `tags:` key. A nested `tags:`
  key is ignored, and saving rewrites the file as a plain list.

## [3.5.0] - 2026-10-02

### Added

- Edit keyboard shortcuts right in **Settings → Shortcuts**: an **Edit** button
  switches the list to a key-capture view where you click a binding and press
  the new combination (modifier-only bindings are set by pressing and releasing
  the modifier). **Save** writes the changes to your own `shortcuts.txt` in the
  user folder, preserving comments; `↺` restores the shipped default. The
  shipped `app/shortcuts.txt` is never modified, so updates keep working.

## [3.4.2] - 2026-10-02

### Fixed

- On a fresh install the **Load a dataset**, **What's new** and **Tip of the
  day** dialogs no longer appear at the same time. They are queued and shown one
  after another (dataset prompt first, then changelog, then tip).

## [3.4.1] - 2026-10-02

### Fixed

- The installer now reliably creates the **`ybe`** alias. A stale `ybe` symlink
  or directory in the launcher folder made `ln` put the link inside it, so
  `yolo-box-editor` was created but `ybe` was not.

## [3.4.0] - 2026-10-02

### Added

- **Daily tip** dialog: one random tip per day, cycling through the shipped list
  without repeating until every tip has been shown.
- Built-in **`update_tags`** action and a shipped **`on_after_save`** hook: after
  a save, the image's tag file is written and any new tag names are added to
  `tags.yaml` (skipped when there is nothing new).
- A per-dataset **Tags folder** setting (Settings → Dataset), saved with the
  view state, defaulting to `tags/` beside `images/` and `labels/`.
- The tag bar warns when a tag on the image is not in `tags.yaml`, or when no
  `tags.yaml` is found, explaining why a tag may look missing.

### Changed

- The Settings **View** tab is now **General**, with a new **Show tip on start**
  toggle.
- The last image is remembered **per split**, so switching back to a split
  resumes the image you were on there.
- The browser console logs the running version on start.
- The README is a lightweight quick start; the detailed reference moved to
  `docs/`.

### Fixed

- Choosing **All splits** no longer snaps back to the previously selected split.

## [3.3.0] - 2026-10-02

### Added

- UI settings (View and Layout preferences, panel sizes and floating-window
  positions) are now also saved on the server, so a browser you have not used
  before starts with the same setup. A value you change in a given browser still
  wins there.

## [3.2.0] - 2026-10-02

### Added

- **Settings → Layout** now has one block per widget (Tags, Boxes, Actions,
  Navigation, Save / Undo) with a **Show** toggle and a **Location** selector.

### Changed

- The tag controls are shown by default; the old **Tags** switch in
  **Settings → View** is gone (use the Tags widget's **Show** toggle instead).

## [3.1.0] - 2026-10-02

### Added

- More dockable widgets: **Actions**, **Navigation** (Prev / counter / Next) and
  **Save / Undo** now dock exactly like Tags and Boxes (default, floating, left,
  right or bottom) from **Settings → Layout** or their title bar. All five are
  listed in the Layout tab.

### Changed

- The bottom panel now disappears when it holds no widget (previously it always
  showed the navigation/save row).
- The box list no longer adds inner padding.

## [3.0.0] - 2026-10-02

### Changed

- The **How to update** dialog now tells you to run **`ybe update`** (alias
  `ybe upgrade`); `ybx.sh` is only the one-time installer. The no-launcher
  fallback (re-run the one-liner) is still offered.

### Removed

- **Breaking:** the installer's `--no-link` option. `yolo-box-editor` and its
  `ybe` alias are now always added to `~/.local/bin` (`--link` is accepted as a
  no-op for old scripts).

## [2.16.0] - 2026-10-02

### Changed

- **Tags** and **Boxes** are now dockable widgets: send them to the left, right
  or bottom panel, or keep them floating. A side docked to the control panel
  stays in it; otherwise a panel opens on the opposite side. Panels appear only
  while they hold a widget. Replaces the old floating-window detach checkboxes.

## [2.15.0] - 2026-10-02

### Changed

- The filter chain moved from the side panel / "Filter chain" modal into a new
  **Filters** tab in **Settings** (⚙).

## [2.14.0] - 2026-10-02

### Changed

- Shortcuts now live directly in **Settings > Shortcuts** (scrollable) instead
  of behind a "Show all shortcuts" button; the separate shortcuts window is gone.

## [2.13.0] - 2026-10-02

### Added

- Automated GitHub release workflow: a push to `main` that changes the major or
  minor part of `app/VERSION` creates the tag and release (patch bumps are tagged
  manually).

## [2.12.0] - 2026-10-02

### Added

- **`ybx.sh uninstall`** (also `ybe uninstall`): stops a running instance,
  removes the launchers, `<dir>/app`, `<dir>/.venv` and `ybx.sh`, and keeps your
  `actions/`, `hooks/`, `filters/`, `scripts/` and `shortcuts.txt`. Add
  `--purge --yes` to delete the whole user folder as well (`--purge` alone asks
  interactively, or refuses when not run from a terminal).

## [2.11.0] - 2026-10-02

### Added

- `ybx.sh update --latest` installs the newest commit on the `main` branch, and
  `ybx.sh update --commit <sha>` pins a specific commit. Both download the
  GitHub archive over HTTP (curl only) — no `git` required.

## [2.10.0] - 2026-10-02

### Added

- `ybx.sh install` / `upgrade` now **start the app** when done (background via
  the launcher, restarting an already-running instance) so it is ready at
  <http://127.0.0.1:5000>. Pass the new `--no-start` flag to skip it. With
  `--no-link` (no launcher) the manual run command is printed instead.

## [2.9.0] - 2026-10-02

### Added

- **Layout settings** (Settings → Layout, remembered per browser):
  - **Panel side** — put the side panel on the left or right (border, resize
    handle, collapsed buttons and notification panel flip with it).
  - **Floating Tags / Boxes** — detach the tags bar or the box list into a
    movable floating window. Drag by the title bar; release near an edge snaps
    it flush, or use the `⇤ ⇧ ⇥ ⇩` dock buttons. Position is remembered per
    window and the `×` button re-attaches the section to the panel/bar.
  - Detaching moves the existing section into the window (its controls keep
    working); the tag window shows only while tags are visible.

## [2.8.0] - 2026-10-02

### Added

- **First-run "Load a dataset" dialog**: with no dataset loaded, the app now
  opens a small modal with a paste-the-path input and a **Load** button (instead
  of opening the whole Settings modal).

### Changed

- **Settings modal restyled with tabs** (View / Dataset / Shortcuts / Updates).
  The Dataset tab puts the recent-dataset dropdown, the path input and the
  **Load** button on one row; the dropdown is hidden when there are no recent
  datasets.
- **Breaking-change warnings replaced by an in-app changelog.** The shipped
  `app/BREAKING.md` machinery (backend parsing, `ybx.sh` warnings, the update
  notice's *Breaking changes* section) is removed. Instead, `app/CHANGES` holds
  short per-version notes, and the app shows the installed version's notes once
  per version on first open (a **What's new** dialog). `/api/config` now returns
  `changelog`; `/api/update-check` no longer returns `breaking_changes` /
  `breaking`, and `ybx.sh check-update` no longer prints `breaking_changes:` /
  `breaking_notes:`.

## [2.7.1] - 2026-10-01

### Fixed

- Breaking-change notes now actually reach a **fresh install**: when no update
  is available the *newest* entry the installed version already contains
  (`version <= current`) is shown (previously only an exact `current` match
  was, so a fresh install of a later release showed nothing). With an update
  available the range `current < version <= latest` is shown as before.

## [2.7.0] - 2026-10-01

### Added

- **Breaking-change warnings** driven by a new shipped `app/BREAKING.md`
  (`<version> | <note>` per line). `ybx.sh check-update` now prints
  `breaking_changes:` and `breaking_notes:` lines, `upgrade` prints the notes as
  a warning before it runs, `install` warns about the installed version's own
  breaking changes, and the in-app update notice shows a **Breaking changes**
  section with the notes. The installed version's own entry is included, so a
  *fresh install* of a breaking release is warned as well.
- `2.6.0` is recorded as a breaking release (`ybe OPTIONS` became
  `ybe start OPTIONS`).

### Fixed

- **Latest-version detection** now takes the highest of the latest release and
  every tag (both in `ybx.sh` and the app), so a newer tag is no longer hidden
  by an older release.

## [2.6.0] - 2026-10-01

### Added

- **Daemon mode**: `ybe` / `yolo-box-editor` now run the app **in the
  background by default**. New commands: `ybe start [--fg] [OPTIONS]`
  (`daemon`/`fg` aliases), `stop`, `restart`, `status` and `logs [-f]`; running
  `ybe` with no arguments prints the help. Foreground stays available via
  `ybe start --fg`. The launcher logic is a shipped template
  (`app/launcher.sh.in`) that `ybx.sh` bakes the install paths into.
- **File logging**: a `setup_logging()` logger plus `--log-file PATH` and
  `--no-reload` flags. Daemon runs log to `<home>/ybe.log` with the PID in
  `<home>/ybe.pid` (both git-ignored); the noisy `/api/presence` heartbeat is
  filtered out of the access log.

## [2.5.0] - 2026-10-01

### Added

- The launchers (`yolo-box-editor` and `ybe`) now handle the maintenance
  subcommands **`version`**, **`check-update`** and **`update`** directly by
  delegating to the installed `ybx.sh`; any other argument still goes to the
  app (e.g. `ybe --data …`). `ybx.sh` accepts `update` as an alias of `upgrade`.

### Fixed

- `ybx.sh upgrade` no longer **downgrades** when the newest published version is
  older than the installed one (e.g. a local/dev build): it now reports "already
  at" and stops.
- Calling `upgrade`/`update` through the installed launcher no longer fails
  copying `ybx.sh` onto itself (`cp: … are the same file`).

## [2.4.0] - 2026-10-01

### Added

- The installed launcher can now also be run as **`ybe`**: `ybx.sh install` /
  `upgrade` (`--link`) add a `ybe` symlink next to `~/.local/bin/yolo-box-editor`.

## [2.3.0] - 2026-10-01

### Added

- **Update check**: the app now looks for a newer version on GitHub at every
  start and re-checks at most once a week (result cached in
  `<home>/.update_check.json`; a check is skipped while the cache is fresh).
  `/api/update-check` reports the cached result and `POST {"force": true}`
  refreshes it; disable the whole check with `--no-update-check`.
- When a newer version is found, a **daily notification** appears (once per day,
  deduped, also recorded behind the bell) with a **How to update** button that
  opens step-by-step instructions for Linux/macOS (`ybx.sh upgrade`) and for
  manual/Windows installs (`git pull` + `pip install -r app/requirements.txt`).
- The **Settings** dialog gained an **Updates** group with the current/latest
  version, a **Check now** button and the **How to update** guide. Toasts can
  now carry an optional action button.

## [2.2.0] - 2026-09-30

### Changed

- **More room for the image**: the full-width top bar is gone. Everything now
  lives in a single collapsible **right column**, top to bottom: the app label
  with the **⚙ Settings**, notifications bell and **Panel** buttons (always
  visible header row), the dataset directory name, the **Split** picker, the
  applied **Filter** names with a `…` button, the per-dataset action buttons (a
  few, with a `…` expander), and the **Boxes** list. The column width is
  draggable; **Panel** collapses everything except the four header items and
  shrinks the column to the header, so the image gets the horizontal space back.
  - The **Read-only**, **Tags** and **Auto-save** switches plus the dataset
    field moved into a **Settings** dialog opened with the gear button (it
    opens automatically when no dataset is loaded).
  - The bottom shortcut bar was replaced by a **Show all shortcuts** entry in
    Settings that opens a modal with the full list.
  - Status toasts now appear at the **bottom center**.
  - The tag controls and the image nav / Undo / Redo / Save controls now share
    a **single bottom row**; the filename label was removed.
  - The add-tag control is now a small `+` button that reveals the input on
    demand, and a `…` button appears when the tag badges overflow the row.
  - The redundant box-count badge was removed from the bottom bar (the count
    stays in the Boxes panel header).

### Added

- **Toasts**: save / dataset / split / filter / tag / hook status messages are
  now floating notifications that never affect the layout. Info and success
  toasts auto-dismiss; errors and warnings stay until dismissed and are
  collected behind a **bell** with an unread badge. The concurrent-use warning
  and the `shortcuts.txt` / `hooks/` validation errors use the same system.

## [2.1.0] - 2026-09-30

### Added

- **`ybx.sh` installer** (replaces `install.sh`): subcommands `install`,
  `upgrade`, `version` and `check-update`. It downloads the latest GitHub
  release, else the newest tag, else the `main` branch, and can install from a
  local checkout or a `.tar.gz` with `--from`. Options `--dir`/`--home`,
  `--version`, `--link`/`--no-link` (link on by default) and `--python`.
- Upgrades replace only `<dir>/app/` **atomically** (staged, validated, then
  swapped with rollback); the user folders and `.venv` are never touched.
- `check-update` prints exactly three lines (`exit code:`, `current_version:`,
  `latest_version:`), exiting `0` when an update is available and `1` when
  current (`2` when the latest version cannot be determined).
- The installer saves a copy of itself to `<dir>/ybx.sh` so the installed app
  can be updated in place.

## [2.0.0] - 2026-09-30

### Changed

- **Split code and user files** (breaking). The app now lives in `app/`
  (`app/app.py`, `app/static/`, `app/templates/`, `app/requirements.txt`,
  `app/VERSION`) and the shipped extension files are `app/actions/`,
  `app/hooks/`, `app/filters/`, `app/scripts/` and `app/shortcuts.txt`. Your own
  files live in the **user folder** (`actions/`, `hooks/`, `filters/`,
  `scripts/`, `shortcuts.txt`), next to `app/`. Upgrades replace only `app/`, so
  user files are never overwritten.
- **User folder resolution**: `--home <dir>` > `$YBX_HOME` > the parent of
  `app.py`. A clone and an install therefore behave the same. The folders are
  created at startup and the path is logged (`[ybe] user dir: …`).
- **`.a.*` convention removed** (breaking): `*.a.yaml`, `*.a.py` and
  `shortcuts.a.txt` are no longer special. Move those files into the user folder
  and drop the `.a` suffix (`actions/Archive.a.yaml` -> `actions/Archive.yaml`).
  User files are still read after the shipped ones and win on a name clash.
- **Run working directory is now the user folder** (breaking), logged before
  each command/filter. Previously it was the app folder. Your own helpers are
  reached relatively as `scripts/…`; the shipped ones as `{APP_DIR}/scripts/…`;
  `{HOME_DIR}` is the user folder. Commands also receive `YBE_HOME`,
  `YBE_APP_DIR`, `YBE_APP_SCRIPT_DIR` and `YBE_USER_SCRIPT_DIR` in their
  environment.
- `.recent_data_yamls.json` and `.view_state.json` now live in the user folder.

### Added

- `--home <dir>` flag and the `YBX_HOME` environment variable.
- `{HOME_DIR}`, `{APP_SCRIPT_DIR}` and `{USER_SCRIPT_DIR}` placeholders and
  per-run `cwd` in the action result payload. Scripts can be reached explicitly
  (`{USER_SCRIPT_DIR}/…`, `{APP_SCRIPT_DIR}/…`) or relatively (`scripts/…`).
- `app/` layout keeps the shipped files in one relocatable directory, ready for
  the upcoming `ybx.sh` installer (Task 2).

## [1.1.0] - 2026-09-29

### Added

- **Linux `install.sh`**: sets up an isolated `.venv`, installs
  `requirements.txt`, and (with `--link`) adds a `yolo-box-editor` command to
  `~/.local/bin`. Supports `--python` and `--venv` overrides.

## [1.0.0] - 2026-09-29

### Changed

- **Filters are now chainable** (breaking). The topbar `Filter` dropdown is
  replaced by a **`Filters` button** that opens a modal with stacked selects
  (up to 8). The selected filters run top to bottom, each narrowing the previous
  one's list; the last result is what the app shows.
- **New filter contract** (breaking): a filter is run as
  `python filters/<Name>.py <data.yaml> <split> <input_pipe> <output_pipe>`
  instead of printing `split/name` lines on stdout. The input pipe holds one
  absolute image path per line (the first filter gets the active split's images);
  the filter writes the paths it keeps to the output pipe. `filters/example.py`
  and personal filters must be migrated.
- A failed filter stops the chain and keeps the previous chain in effect; filter
  scratch files are deleted after each run. New `--keep-filter-pipes` flag keeps
  them for debugging.

### Added

- **Server-side built-in actions (`backend_*`)**: a `steps` / `after_success`
  entry can name a whitelisted server-side action, run inline by the backend
  with no browser round trip. `backend_rescan_images` re-scans the image folders
  and re-applies the active filter, so an action (e.g. `Archive`) can guarantee
  the server list is fresh; an unknown `backend_*` name is rejected.
- **`GET /api/images`** returns the current in-memory image list without
  touching the disk, and the new app action **`app_reload_images_list`** applies
  it to the UI. Use it after `backend_rescan_images` so the disk is scanned once,
  server-side.
- **Per-dataset view persistence** (`.view_state.json`, git-ignored): the active
  split and filter are saved per `data.yaml` and restored when the app resumes
  that dataset, so a restart (e.g. the Flask `--debug` reloader) no longer drops
  the view of an already-open browser tab.
- **Concurrent-client warning**: the UI pings the new `POST /api/presence`
  route and, while more than one tab, browser or machine is using a running
  instance, shows a dismissible banner ("Another user is using this app. It is
  designed for one user at a time and is not meant to be served to multiple
  clients..."). It is informational only — nothing is blocked and all existing
  behavior is unchanged. A client that stops pinging for 15 s is
  considered gone (e.g. a closed tab), and a page unload sends a best-effort
  removal via `navigator.sendBeacon`.
- **`{PIPE_PATH}` action/hook placeholder**: a per-run scratch file that every
  step and every action reached through `after_success` can read and write to
  pass data between each other. It is created in the system temp dir (empty) at
  the start of a run and deleted by the backend once the whole run has finished,
  success or failure. Pass the new `--keep-pipe` flag to keep the file after
  each run (useful for debugging). The run's path is reported by
  `/api/actions/run` as `pipe_path`.
- **Action executions are now driven by the backend.** `/api/actions/run` runs
  the root `steps` and then the whole `after_success` list as one ordered queue,
  executing server-side entries itself and pausing only at a client-side `app_*`
  entry, which it returns as `client_action` with an execution `uid`. The UI runs
  that action and posts `{uid, result}` to resume, so a mixed list keeps its
  exact order while the backend still owns the run (and its `{PIPE_PATH}` file).
  Cascades are capped at 8 actions per run and unknown `app_*` / `action_*` names
  are rejected server-side. `PIPE_PATH` is shared by every step and every
  server-side action of the run.
- **`steps` and `after_success` now accept the same entries.** Each entry is an
  `app_*` action (run in the UI, pausing the run), `action_<Name>` (run that
  action inline, with its own steps — the prefix keeps it from clashing with a
  shell command), or anything else, which is a shell command (so `after_success`
  can run commands too, not only actions). A run is a single queue, so any entry
  can stop for the UI and continue on resume.
- **Resume the previous session on start**: running `python app.py` without
  `--data` reopens the dataset last used (the newest entry of
  `.recent_data_yamls.json` that still exists); pass the new `--no-resume` flag
  to start on the settings screen instead. The active split (with or without a
  filter) is now remembered per dataset too, alongside the already-remembered
  filter and last image, and the topbar switches (`Tags`, `Auto-save`, `Boxes`
  panel and the box-overlay show/hide) are restored, so the UI comes back as it
  was left.
- **`--debug` flag**: when passed to `python app.py`, the UI logs verbose
  messages to the browser console (prefixed `[ybe]`) for the loaded config,
  image loads, saves, tag writes, user actions / `after_success` chains, hooks,
  image-list rescans and box edits, plus uncaught errors. The active state is
  reported by `/api/config` as `debug`.
- **Script-based image-list filters** (`filters/` folder, one Python script per
  filter): the topbar `Filter` dropdown (shown once a `data.yaml` is loaded)
  narrows the loaded image list to what the script returns. A filter is run as
  `python filters/<Name>.py <data.yaml> <split>` (the split is `""` for *All
  splits*) and prints one `split/name` per line; order is preserved, blank lines
  ignored, duplicates dropped, unknown lines skipped with a notice. An active
  filter supersedes split filtering and re-runs on split change and on rescan;
  failures/timeouts (120 s) are reported. Personal `filters/*.a.py` overrides
  win on a name clash and are git-ignored. The active filter is remembered in
  `localStorage` and restored on load, even after a server restart. New
  `POST /api/filter` route; `/api/config` reports `filters`, `active_filter` and
  `filter_error`.
- **Auto-save switch** (topbar, remembered in `localStorage`): when on, the
  current image's labels are saved automatically after each edit (rapid edits
  coalesce into one write). Prev/Next and the counter jump then skip the
  save/discard prompt and flush any pending save first, staying on the image if
  the write fails.
- **Event hooks in a new `hooks/` folder**: a YAML file named
  `on_<event>.yaml` runs on an app event instead of a toolbar button / shortcut;
  when the file name names no event, the `event_name:` key is used, and
  `active: false` skips the file. Available events: `images_list_loaded`,
  `image_loaded`, `prev`, `next` (fire on the image being left), `before_save`
  (failure aborts the save), `after_save`, `box_created`, `box_deleted`,
  `box_edited`. Hooks use the same `steps` / `after_success` and placeholders as
  actions; steps run with the working directory set to the app's folder and a
  new `{APP_DIR}` placeholder resolves to it, so hooks can call `scripts/`
  reliably. A successful hook reports in a new bottom status bar (auto-hides); a
  failed hook opens the result modal. A `steps` hook with no resolvable event is
  reported as an error (the comments-only `hooks/example.yaml` is ignored
  silently and shows no error). They are opt-in and cannot be bound to a key or
  named in `after_success`.
- **`after_success` may now chain into another (non-hook) action**, not only app
  actions; cascades are capped at 8 levels to prevent recursion.
- **User actions now live in an `actions/` folder, one YAML file per action**
  (name from the optional `name:` key, else the file name): multi-step actions
  whose commands run one after another and stop on the first failure, plus an
  `after_success` hook that runs app actions client-side after everything
  succeeded. Personal files are `actions/*.a.yaml` (git-ignored, read last and
  win on a name clash). The old `actions.txt` / `actions.a.txt` format is
  **dropped**.
- **New action placeholder `{DATA_YAML_PATH}`** (path of the loaded data.yaml),
  and action steps now run with the working directory set to the app's folder,
  so relative script paths resolve predictably.
- **New action placeholders `{DATASET_PATH}` and `{IMAGE_INDEX}`** (the latter
  1-based, matching the UI counter), alongside `{IMAGE_PATH}` / `{LABEL_PATH}`;
  all are shell-quoted.
- **App actions `app_refresh_images_list` / `app_refresh_image`** (no default
  keys; bind them in `shortcuts.a.txt`, or trigger them from a YAML action's
  `after_success`): re-scan the image folders (navigation stays on the same
  index, clamped) and re-fetch the current image (cache-busted).
- `POST /api/images/rescan` endpoint; `/api/image/<idx>` responses are served
  with `Cache-Control: no-store`; a failed image load clears the canvas instead
  of leaving a stale frame.
- **Resume at the last image reached** (per dataset) on reload, and the
  `current / total` counter is now an input — type a number + Enter to jump.
- **`app_show_hide`** (default `.`) toggles the box overlay on the image; kept
  working in read-only mode.
- **Per-image tags**: an opt-in topbar `Tags` switch reveals a tag bar below the
  image. Dataset tags come from a `tags.yaml` beside `data.yaml`
  (`tags:` list); per-image tags live in a `tags/` folder beside `images/` and
  `labels/` (`images/train` → `tags/train`, one `<stem>.txt` per image, one tag
  per line).
- Tag bar badges: available tags are clickable toggles — green/active when on
  the current image, outlined/inactive otherwise. `+ Add tag` appends a new name
  to `tags.yaml` (then attaches it), and tag edits auto-save to the image file.
- `Alt+1` … `Alt+9` toggles the tag at that 1-based position in `tags.yaml`;
  using it also enables tagging.
- Server routes `GET/POST /api/tags.yaml` and `GET/POST /api/tags/<idx>`
  (read-only mode rejects both writes); `/api/config` now reports `tags` and a
  `tags_dir` per split.
- **Force-draw modifier (`app_force_draw`, default `Ctrl`)**: hold the configured
  modifier and drag to draw a new box even inside / on top of an existing one.
  The modifier comes from `shortcuts.txt` / `shortcuts.a.txt` (`Ctrl`/`Meta` are
  the Linux-safe choices; `Alt`+drag is often swallowed by window managers).
- **Fix / unfix boxes (`app_fix_box`, default `F`)**: a fixed box is drawn with a
  dashed grey outline and no handles and ignores dragging (moving / resizing),
  while still being clickable, selectable and deletable via the side-panel `F`
  toggle. The flag is transient — it is never saved and is cleared when the image
  changes.

### Changed

- **Per-image requests are addressed by `split/name`, not by index.**
  `/api/image`, `/api/labels` and `/api/tags` now take `?key=<split>/<name>`, and
  `/api/actions/run` takes `target=<split>/<name>`; the old `<int:idx>` routes
  and the `idx` body field are removed. An index was only meaningful while the
  client and server lists matched — after a restart or a filter change the same
  index could mean a different file. An old cached `app.js` will 404 until the
  page is reloaded.
- **The current image is tracked by path, not index, across list changes.** When
  an action (`Archive`) or a re-applied filter rebuilds the image list,
  `app_refresh_images_list` now looks the image up by `split/name`; if it was
  removed it falls back to the first still-present image that followed it, then
  to the clamped index. Changing the split or filter preserves the current image
  the same way. This is filter/order agnostic, so browsing a filter whose result
  changes as you review (e.g. `no_revised`) no longer jumps to an arbitrary
  image, and the remembered last image (already stored by path) is unaffected.

### Fixed

- **An action or hook could act on the wrong image — and `Archive` could move
  the wrong file.** The request only carried the image's position (`idx`), which
  the backend resolved against its own list. If the browser tab and the server
  had diverged (a `--debug` reloader restart dropped the server's active filter
  while the open tab kept its filtered list), position `5` meant one file on
  screen and another on the server, so the archive/delete hit the wrong file and
  the one on screen stayed. Requests now name the image (`split/name`) and the
  server acts on exactly that file.
- The shortcuts bar's `…` button did nothing: its popup is anchored above the
  bar but the bar clipped it with `overflow: hidden`, so the menu was rendered
  invisibly. The bar no longer clips its popup (the shortcut list itself still
  clips its own overflowing items).
- Hidden boxes (`.`) no longer intercept the mouse: their invisible rectangles
  and delete / class buttons used to swallow clicks and could be moved or
  deleted while not shown.
- After an action that changes the image list (e.g. `Archive` chaining
  `app_refresh_images_list` and `app_refresh_image`), the canvas no longer keeps
  showing the removed image. `loadImage` now cache-busts its image URL like
  `app_refresh_image`, so the stale decoded frame can't be restored when the
  index the two actions use is the one that was just archived.
- Start-up no longer hangs in an endless split-switch/reload loop when the
  remembered last image lives in a different split than the remembered active
  split (e.g. an image in `val` while the saved view is *All splits*).
  `maybeRestoreView` only restores a remembered split when the server has none,
  so it no longer overrides the split `resumeLastImage` just set (especially not
  back to `null`), and `resumeLastImage` gives up after one switch attempt.

## [0.5.0] — 2026-09-21

First documented release. Labelling UI reworked, user actions and configurable
shortcuts added, strict read-only mode, and per-box editing moved into the
side panel.

### Added

- Side **Boxes panel** on the right edge of the canvas (hideable via the
  `Boxes` toggle in the topbar). Shows every box of the current image.
- **In-place box editing**: each row carries its class dropdown,
  `cx cy w h` inputs and a `×` delete button. Controls are disabled until the
  row (or its box on the canvas) is selected; selecting another box — or
  pressing `Esc` — disables them again. Coordinates clamp to `0..1` and update
  the canvas live.
- Two-line box rows so the point coordinates fit on screen.
- **User-definable shell actions** in `actions.txt`, rendered as buttons in the
  topbar (`{IMAGE_PATH}` / `{LABEL_PATH}` placeholders, shell-quoted).
- **Configurable keyboard shortcuts** in `shortcuts.txt`
  (`ACTION_NAME <SHORTCUT> label` syntax), covering built-in app actions and
  user actions; invalid action names produce a dismissible error banner.
- Per-user override files **`actions.a.txt`** / **`shortcuts.a.txt`**, read
  after the shipped files and winning name clashes (never shipped, git-ignored).
- **Read-only mode** via the topbar switch or `--readonly` CLI flag (locked on +
  server-side label-write rejection).
- **Undo / Redo** (`Z` / `Y`), with buttons enabled by the dirty state.
- Split filter (`train` / `val` / `test` / all) and recent `data.yaml` list.

### Changed

- Settings bar (data.yaml input) is hidden once a dataset loads; changed via a
  `Change dataset` button pinned top-right.
- `Read-only` switch and `Change dataset` moved into the topbar, alongside the
  `Boxes` panel toggle.
- Shortcuts bar moved to the bottom with an overflow `…` menu.
- Image nav bar (prev / next / filename / box count / save) below the canvas.
- `Esc` only drops a just-drawn box; existing boxes are merely deselected.
- `Shift` cycles selection to the next box; `/` opens the class picker for the
  selected box.
- Class dropdown on the canvas replaced by a per-box `/` button.

## [0.4.0] — 2026-09-17

Original labelled pipeline (before the UI rework; renamed from
`yolo-labeller`).

- Flask app serving a single-page YOLO label editor; navigate images across
  `train`/`val`/`test`, draw/edit boxes with 8 drag handles, class list popup on
  draw, save back to `<stem>.txt`.
- Remote branches were GitHub, then Gitea (migrated mid-history).

[Unreleased]: https://github.com/tabebqena/yolo-box-editor/compare/0.5.0...HEAD
[0.5.0]: https://github.com/tabebqena/yolo-box-editor/releases/tag/0.5.0
[0.4.0]: https://github.com/tabebqena/yolo-box-editor/releases/tag/0.4.0
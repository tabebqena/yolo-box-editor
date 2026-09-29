# Changelog

All notable changes to **yolo-box-editor** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

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
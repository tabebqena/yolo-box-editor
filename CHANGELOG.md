# Changelog

All notable changes to **yolo-box-editor** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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

- **The current image is tracked by path, not index, across list changes.** When
  an action (`Archive`) or a re-applied filter rebuilds the image list,
  `app_refresh_images_list` now looks the image up by `split/name`; if it was
  removed it falls back to the first still-present image that followed it, then
  to the clamped index. Changing the split or filter preserves the current image
  the same way. This is filter/order agnostic, so browsing a filter whose result
  changes as you review (e.g. `no_revised`) no longer jumps to an arbitrary
  image, and the remembered last image (already stored by path) is unaffected.

### Fixed

- Hidden boxes (`.`) no longer intercept the mouse: their invisible rectangles
  and delete / class buttons used to swallow clicks and could be moved or
  deleted while not shown.
- After an action that changes the image list (e.g. `Archive` chaining
  `app_refresh_images_list` and `app_refresh_image`), the canvas no longer keeps
  showing the removed image. `loadImage` now cache-busts its image URL like
  `app_refresh_image`, so the stale decoded frame can't be restored when the
  index the two actions use is the one that was just archived.

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
# Changelog

All notable changes to **yolo-box-editor** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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
- **Event hooks `on_app_hook_*`**: an action whose name starts with
  `on_app_hook_` runs on an app event instead of a toolbar button / shortcut.
  Available: `on_app_hook_images_list_loaded`, `on_app_hook_image_loaded`,
  `on_app_hook_prev`, `on_app_hook_next` (fire on the image being left),
  `on_app_hook_before_save` (failure aborts the save), `on_app_hook_after_save`,
  `on_app_hook_box_created`, `on_app_hook_box_deleted`, `on_app_hook_box_edited`.
  A successful hook reports in a new bottom status bar (auto-hides); a failed
  hook opens the result modal. They are opt-in (defined by a file in
  `actions/`); they cannot be bound to a key or named in `after_success`.
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
# yolo-box-editor

> **Simple · self-hosted · fast — draw and edit YOLO boxes with keyboard, mouse, or both.**

A small Flask-served web app for labelling images in
[YOLO](https://docs.ultralytics.com/datasets/detect/) format.

Version **0.6.0** · [CHANGELOG.md](CHANGELOG.md) · [LICENSE](LICENSE) (MIT with a
non-commercial-use condition, no warranty on usage) · new to labelling?
read [TUTORIAL.md](TUTORIAL.md) first.

## Features

- **One-file setup**: point the app at a single `data.yaml` from the command
  line or the UI. No database, no build step.
- **Recent list**: the last 10 opened `data.yaml` paths are remembered in
  `.recent_data_yamls.json` next to `app.py`; reopen one from the *Recent…*
  dropdown or type a new path.
- **Browse** across `train` / `val` / `test` with Prev/Next buttons or the
  `→` / `←` arrow keys; the current image is shown as `<split>/<filename>`.
  The `current / total` counter is an input — type a number and press Enter to
  jump straight to that image. The app also resumes at the last image you
  reached (per dataset) when you reload.
- **Split filter**: narrow navigation to a single split, or "All splits".
- **Filters**: narrow the loaded image list with a script from the `filters/`
  folder (shown once a `data.yaml` is loaded). See [Filters](#filters).
- **Labels** are drawn on the image as boxes; a class list pops up when a new
  box is drawn.
- **Hide / show boxes**: press `.` to toggle the box overlay, so you can inspect
  the raw photo underneath (works in read-only mode too; boxes stay intact).
- **Draw & edit boxes on the canvas**: drag to draw, click to select, drag
  inside to move, drag any of the 8 handles to resize, click the `/` on a box
  to change its class.
- **Boxes panel** (right edge, `Boxes` toggle): one row per box, each with its
  class dropdown, `cx cy w h` numeric inputs and a `×` delete button. Controls
  are disabled until the row — or its box on the canvas — is *selected*;
  selecting another box or pressing `Esc` disables them again. Typing clamps
  values to `0..1` and updates the canvas live; while a coordinate input is
  focused its value is highlighted on the image in orange.
- **Keyboard-first row editing**: with a box selected, `Tab` cycles between the
  class select and the four coordinate inputs of its row; `Esc` deactivates the
  row. `Shift` selects the next box (resuming from the last active one after
  `Esc`).
- **Undo / Redo / Save**: `z` undoes, `y` redoes, `s` saves — Save is enabled
  only while the image has unsaved changes.
- **Auto-save** (topbar switch, remembered per browser): after each edit the
  current image's labels are saved automatically (edits are coalesced into one
  write). While it is on, Prev/Next and the counter jump no longer ask to
  save/discard — any pending write is flushed first (navigation is kept on the
  image if that write fails).
- **Read-only mode**: pass `--readonly` (or tick the topbar switch) to browse as
  a pure viewer; drawing, editing and saving stop, and label writes are also
  rejected server-side. The switch is locked on when started with `--readonly`.
- **User actions**: custom commands defined in the `actions/` folder, one YAML
  file per action, run on the current image (with a confirmation) and show
  stdout / stderr / exit code in a popup. `{IMAGE_PATH}`, `{LABEL_PATH}`,
  `{DATASET_PATH}`, `{DATA_YAML_PATH}` and `{IMAGE_INDEX}` are substituted and
  shell-quoted — see
  [User actions](#user-actions). App updates overwrite the shipped files; keep
  personal actions in `actions/*.a.yaml` (see below), which are read after the
  others and win on name clashes.
- **Event hooks**: actions named `on_app_hook_*` run on app events instead of a
  button — e.g. `on_app_hook_after_save` or `on_app_hook_box_created`. See
  [Hooks](#hooks).
- **Configurable shortcuts**: bind keys in `shortcuts.txt` with
  `ACTION_NAME <SHORTCUT> label`. Every app action and your action names
  can be bound; invalid names are rejected with a dismissible banner.
  Personal remaps go in `shortcuts.a.txt` (same format, read after
  `shortcuts.txt`).
- **Tags** (opt-in via the topbar `Tags` switch): a tag bar below the image
  shows the dataset's tags as clickable badges — click to toggle a tag on the
  current image, `+ Add tag` appends a brand-new name to `tags.yaml`, and
  `Alt+1..9` toggles the matching tag by number. Active badges look different
  from inactive ones. See [Tags](#tags) below.

## Keyboard shortcuts & app actions

The 14 built-in app actions are defined in `app.py` (`APP_ACTIONS`) and
implemented in `static/app.js`. Rebind them in `shortcuts.txt` (or
`shortcuts.a.txt`); the names themselves are fixed. They are also the valid
values for an action's `after_success` (see [User actions](#user-actions)) —
they are **not** valid in `steps`, which are shell commands.

| Action | Default key | What it does |
| ------ | ----------- | ------------ |
| `app_prev` | `←` | previous image |
| `app_next` | `→` | next image |
| `app_del` | `Delete` / `Backspace` | delete selected box |
| `app_drop` | `Esc` | drop just-drawn box / deselect (also closes the class picker) |
| `app_undo` | `Z` | undo |
| `app_redo` | `Y` | redo |
| `app_save` | `S` | save labels |
| `app_ch_box` | `/` | open the class picker for the selected box |
| `app_sel_box` | `Shift` | select next box (resumes from the last active one after `Esc`) |
| `app_sel_points` | `Tab` | cycle box-row controls: class → cx → cy → w → h |
| `app_escape` | `Esc` | deactivate the focused row control |
| `app_show_hide` | `.` | toggle the box overlay on the image |
| `app_refresh_images_list` | — | re-scan the image folders; stay on the same index (clamped) |
| `app_refresh_image` | — | re-fetch the current image (cache-busted) |

`app_refresh_images_list` and `app_refresh_image` have **no default keys** —
bind them in `shortcuts.a.txt` (e.g. `app_refresh_image <F5>`) or call them
from a YAML action's `after_success`.

Editing actions (`app_del`, `app_save`, `app_undo`, `app_redo`, `app_ch_box`)
do nothing in read-only mode; navigation, `app_drop` and `app_show_hide` still
work.

`Alt+1`…`Alt+9` toggles the tag at that 1-based position in `tags.yaml`; it is
built in, not an `app_*` action.

Only `Tab` and the two `Esc` roles (plus popup/menu closing) are handled
specially while typing in inputs; all other shortcuts are ignored while an
input/select is focused. Modifiers are `Ctrl`, `Alt`, `Shift`, `Meta` joined
with `+`.

## Run

```bash
git clone git@github.com:tabebqena/yolo-box-editor.git
cd yolo-box-editor
pip install -r requirements.txt
python app.py --data /path/to/data.yaml
python app.py --data /path/to/data.yaml --readonly   # viewer only
```

Open <http://127.0.0.1:5000>. You can also leave out `--data` and paste the
`data.yaml` path into the settings bar, then click *Load data.yaml*.

## data.yaml format

```yaml
path: /path/to/dataset_root      # optional; defaults to the data.yaml directory
train: images/train              # relative to `path`
val: images/val
test: images/test                # optional

nc: 3
names: ['cat', 'dog', 'bird']    # one-line list, or a block form
```

- `path` defaults to the folder containing `data.yaml`.
- `train`, `val`, `test` are image folders. For each one the labels folder is
  the same path with an `images` segment replaced by `labels`
  (`images/train` → `labels/train`), or a sibling `labels/<name>` when no
  `images` segment exists.
- Class names come from `names:`. If absent, class names are derived from the
  highest class id found in existing label files.

## Label format

Each image `foo.jpg` has a label file `foo.txt` in the corresponding labels
folder. Each line:

```
<class_id> <x_center> <y_center> <width> <height>
```

Coordinates are normalized to `0..1` relative to the image dimensions.

## User actions

Each action is one YAML file in the `actions/` folder (next to `app.py`), shown
as a button in the topbar. The action's name is its top-level `name:` key, or
the file name without extension when omitted.

```yaml
# actions/Remove.a.yaml — a personal action, not shipped with the repo
steps:                  # one command per line; stop on the first failure
  - rm -f {IMAGE_PATH}  # do NOT put quotes around {PLACEHOLDERS}; the app
  - rm -f {LABEL_PATH}  # shell-quotes them for you
after_success:          # app actions to run, one after another
  - app_refresh_images_list
```

```yaml
# actions/EditImage.yaml — name: is optional; here it defaults to "EditImage"
name: EditImage
steps:
  - gimp {IMAGE_PATH}   # open the image in an external editor
after_success:
  - app_refresh_image   # reload the file you just edited, no full refresh
```

Each step runs in a shell with the placeholders substituted and quoted; stdout /
stderr / exit code are shown in the popup. On the first failing step the
remaining ones are skipped and the error is reported.

Placeholders (leave them unquoted):

| Placeholder       | Value                                                        |
| ----------------- | ------------------------------------------------------------ |
| `{IMAGE_PATH}`    | path of the current image                                    |
| `{LABEL_PATH}`    | path of the current image's label file (may not exist yet)   |
| `{DATASET_PATH}`  | root path of the loaded dataset                              |
| `{DATA_YAML_PATH}`| path of the loaded data.yaml                                 |
| `{IMAGE_INDEX}`   | 1-based position of the current image (matches the counter)  |

Files ending in `.a.yaml` are *yours*: they are read after the shipped files,
win on a name clash (matched by action name, so `name:` can retarget an
override), and are git-ignored so app updates never touch them. A file with
neither `steps` nor `after_success` is ignored — `actions/example.yaml` is such
a template.

**`after_success`** is a list of *app actions* (the same `app_*` names used for
keyboard shortcuts) **or other non-hook actions** that run client-side after
every step succeeded. They run in order; on an error the chain stops, the
message is shown and logged to the browser console. An action can therefore
chain into another action (a cascade is capped at 8 levels). Useful app actions:

- `app_refresh_images_list` — re-scan the image folders; navigation stays on the
  same index (clamped), so a removed image disappears instead of 404ing forever.
- `app_refresh_image` — re-fetch the current image from disk (cache-busted),
  e.g. after an external editor saved a new version. Image responses are served
  with `Cache-Control: no-store`, so you never see a stale frame.

Event hooks (`on_app_hook_*`) may **not** appear in `after_success` — they are
event-driven only. `after_success` entries take no arguments.

## Hooks

An action whose name starts with `on_app_hook_` is an **event hook**: instead of
a toolbar button it runs when the matching app event happens. They are otherwise
ordinary actions — same `actions/` YAML file, same `steps` / `after_success`
and same placeholders. A successful hook reports in the **bottom status bar**
(auto-hides after a few seconds); a failed hook opens the result **modal**. They
are opt-in: no file, no hook.

| Hook | Fired when |
| ---- | ---------- |
| `on_app_hook_images_list_loaded` | the image list is (re)loaded |
| `on_app_hook_image_loaded` | an image is opened in the editor |
| `on_app_hook_prev` | before navigating to the previous image |
| `on_app_hook_next` | before navigating to the next image |
| `on_app_hook_before_save` | just before labels are written — a failure **aborts the save** |
| `on_app_hook_after_save` | after a successful label write |
| `on_app_hook_box_created` | a box was drawn |
| `on_app_hook_box_deleted` | a box was removed |
| `on_app_hook_box_edited` | a box was moved / resized / reclassed (committed edits) |

```yaml
# actions/on_app_hook_after_save.yaml — run a script after every save
steps:
  - touch {DATASET_PATH}/saved.log
```

Hooks are event-only: they are never shown as buttons and cannot be bound in
`shortcuts.txt` (that is reported as an error). A hook whose `after_success`
refreshes the image list cannot re-trigger itself — re-entrant runs of the same
hook are skipped.

## Tags

YOLO has no canonical tagging scheme, so this app defines a minimal one. It is
opt-in: flip the topbar **Tags** switch to show a tag bar below the image.

- **`tags.yaml`** lives next to `data.yaml` and holds the dataset's available
  tags under a single key:

  ```yaml
  tags:
    - fire
    - smoke
    - dangerous
  ```

- **Per-image tags** live in a `tags/` folder beside `images/` and `labels/`
  (same derivation: `images/train` → `tags/train`). Each image `foo.jpg` gets
  `tags/train/foo.txt` with one tag name per line; an empty/absent file means
  "no tags".

- **Tag bar**: every available tag is a clickable badge. A badge is *active*
  (green) when the tag is on the current image and *inactive* (outlined) when it
  is not; clicking toggles it and writes the image's tag file immediately. Tags
  that exist only on an image (not in `tags.yaml`) are shown as active badges
  too.
- **Add a tag**: type a name in the box and click `+ Add tag` (or press
  `Enter`). If the name is not yet in `tags.yaml` it is appended there first,
  then attached to the image; existing names are attached without duplication.
  Removing a tag from an image never deletes it from `tags.yaml`.
- **Keyboard**: `Alt+1` … `Alt+9` toggle the tag at that 1-based position in
  `tags.yaml`. Using the shortcut also turns tagging on so the bar is visible.
- Tag writes are blocked in read-only mode.

## Filters

A **filter** narrows the loaded image list to the images a script returns. The
topbar `Filter` dropdown (next to `Split`) appears once a `data.yaml` is loaded;
pick a filter to apply it, or `No filter` to clear it. An active filter
supersedes the split's own filtering — the split is passed to the filter as its
input, and the returned list is exactly what the app shows (count, Prev/Next,
the counter jump and resume all follow it).

Each filter is one **Python script** in the `filters/` folder, run as:

```bash
python filters/<Name>.py <data.yaml> <split>
```

- `<data.yaml>` — path of the loaded dataset's `data.yaml`.
- `<split>` — `train` / `val` / `test`, or an empty string when the UI is on
  *All splits* (the filter decides what to return then).

The script must print one `split/name` per line, e.g.:

```
train/a.jpg
val/b.png
```

The app keeps those images **in that order** (handy for ranking), ignores blank
lines and drops duplicates; a line whose image is not in the dataset is skipped
and a notice is shown. A non-zero exit code or a timeout (120 s) is reported as
a filter failure and the previous filter (if any) stays active.

Filters re-run when you pick one, when you change the split (while one is
active), and after an image-list rescan. The active filter is remembered in your
browser and restored when you reopen the app — even after a server restart.

Personal filters live in `filters/*.a.py` (git-ignored, read after the shipped
files, win on a name clash). `filters/example.py` is a comments-only template
documenting the contract.

## Development

A single Flask module (`app.py`, ~750 lines) with a hand-rolled `data.yaml`
parser (no PyYAML needed to run). The UI is `index.html` + `app.js` + `style.css`
and needs no build step.

Behaviour checks live in `tests/` and are run from the repo root:

```bash
python -m pytest -q
```

See also: [TUTORIAL.md](TUTORIAL.md), [CHANGELOG.md](CHANGELOG.md),
`VERSION`, `LICENSE`.
# yolo-box-editor

> **Simple · self-hosted · fast — draw and edit YOLO boxes with keyboard, mouse, or both.**

A small Flask-served web app for labelling images in
[YOLO](https://docs.ultralytics.com/datasets/detect/) format.

Version **2.0.0** · [CHANGELOG.md](CHANGELOG.md) · [LICENSE](LICENSE) (MIT with a
non-commercial-use condition, no warranty on usage) · new to labelling?
read [TUTORIAL.md](TUTORIAL.md) first.

## Features

- **One-file setup**: point the app at a single `data.yaml` from the command
  line or the UI. No database, no build step.
- **Recent list**: the last 10 opened `data.yaml` paths are remembered in
  `.recent_data_yamls.json` in your user folder; reopen one from the *Recent…*
  dropdown or type a new path. Starting with a plain run (no `--data`) reopens
  the last dataset automatically — pass `--no-resume` to get the settings screen
  instead.
- **Browse** across `train` / `val` / `test` with Prev/Next buttons or the
  `→` / `←` arrow keys; the current image is shown as `<split>/<filename>`.
  The `current / total` counter is an input — type a number and press Enter to
  jump straight to that image. The app also resumes at the last image you
  reached (per dataset) when you reload.
- **Split filter**: narrow navigation to a single split, or "All splits".
- **Filters**: chain scripts from the `filters/` folder to narrow the loaded
  image list (shown once a `data.yaml` is loaded). See [Filters](#filters).
- **Labels** are drawn on the image as boxes; a class list pops up when a new
  box is drawn.
- **Hide / show boxes**: press `.` to toggle the box overlay, so you can inspect
  the raw photo underneath (works in read-only mode too; boxes stay intact).
  Hidden boxes ignore the mouse, so an unseen box can never be moved or deleted.
- **Draw & edit boxes on the canvas**: drag to draw, click to select, drag
  inside to move, drag any of the 8 handles to resize, click the `/` on a box
  to change its class. To draw a new box inside / on top of an existing one,
  hold the force-draw modifier (default `Ctrl`) and drag — it is configurable
  via `app_force_draw`.
- **Fix boxes**: press `F` (or the row's `F` button) to fix the selected box.
  A fixed box is drawn with a dashed grey outline and no handles: it ignores
  dragging (moving / resizing) but can still be clicked, selected and deleted,
  which lets you protect it while drawing inside it. Fixing is transient — it
  is never saved and is cleared when the image changes.
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
- **Auto-save** (Settings → View switch, remembered per browser): after each edit the
  current image's labels are saved automatically (edits are coalesced into one
  write). While it is on, Prev/Next and the counter jump no longer ask to
  save/discard — any pending write is flushed first (navigation is kept on the
  image if that write fails).
- **Read-only mode**: pass `--readonly` (or tick the Settings switch) to browse as
  a pure viewer; drawing, editing and saving stop, and label writes are also
  rejected server-side. The switch is locked on when started with `--readonly`.
- **Concurrent-use warning**: one running instance keeps a single dataset/view
  state, so it is meant for one user at a time. While more than one tab, browser
  or machine is connected, every client shows a dismissible *"Another user is
  using this app"* notification; it is only a warning — nothing is blocked, and
  simultaneous edits can still overwrite each other. **This app is designed to
  be used by one user at a time and is not designed to be served to multiple
  clients.**
- **User actions**: custom commands defined in your `actions/` folder, one YAML
  file per action, run on the current image (with a confirmation) and show
  stdout / stderr / exit code in a popup. `steps` may mix shell commands with
  built-in app actions and other actions (referenced as `action_<Name>`); the
  backend runs the queue and pauses for the UI at each app action. `{IMAGE_PATH}`,
  `{LABEL_PATH}`, `{DATASET_PATH}`, `{DATA_YAML_PATH}`, `{IMAGE_INDEX}`,
  `{APP_DIR}`, `{HOME_DIR}`, `{APP_SCRIPT_DIR}`, `{USER_SCRIPT_DIR}` and
  `{PIPE_PATH}` are substituted and shell-quoted — see
  [User actions](#user-actions). App updates only replace the shipped `app/`
  folder, so your files in the user folder are never touched.
- **Event hooks**: YAML files in your `hooks/` folder, named `on_<event>.yaml`,
  run on app events instead of a button — e.g. `on_after_save` or
  `on_box_created`. See [Hooks](#hooks). Steps and filters run with the working
  directory set to your user folder (logged to the server console).
- **Configurable shortcuts**: bind keys in `shortcuts.txt` with
  `ACTION_NAME <SHORTCUT> label`. Every app action and your action names
  can be bound; invalid names are rejected with a dismissible notification. Your
  `shortcuts.txt` lives in the user folder and is read after the shipped one.
- **Tags** (opt-in via the Settings `Tags` switch): a tag bar below the image
  shows the dataset's tags as clickable badges — click to toggle a tag on the
  current image, `+ Add tag` appends a brand-new name to `tags.yaml`, and
  `Alt+1..9` toggles the matching tag by number. Active badges look different
  from inactive ones. See [Tags](#tags) below.

## Keyboard shortcuts & app actions

The 17 built-in app actions are defined in `app/app.py` (`APP_ACTIONS`) and
implemented in `app/static/app.js`. Rebind them in your `shortcuts.txt`; the
names themselves are fixed. They are also the valid
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
| `app_show_hide` | `.` | toggle the box overlay on the image (hidden boxes ignore the mouse) |
| `app_fix_box` | `F` | fix / unfix the selected box (transient: never saved, reset on image change) |
| `app_force_draw` | `Ctrl` | held modifier, not a key: hold it and drag to always draw a new box (configurable, e.g. `<Alt>`) |
| `app_refresh_images_list` | — | re-scan the image folders; stay on the same image by path (clamped when gone) |
| `app_reload_images_list` | — | re-read the current list from the server **without** re-scanning the disk (use after a `backend_*` entry already rescanned) |
| `app_refresh_image` | — | re-fetch the current image (cache-busted) |

`app_refresh_images_list`, `app_reload_images_list` and `app_refresh_image` have
**no default keys** — bind them in your `shortcuts.txt` (e.g. `app_refresh_image <F5>`)
or call them from a YAML action's `after_success`.

`app_force_draw` is special: its binding is a *modifier* (`Ctrl`, `Alt`,
`Shift`, `Meta`, or a `+`-joined combination), not a key. `Ctrl`/`Meta` are the
Linux-safe defaults — many window managers swallow `Alt`+drag — and `Shift` is
already used for selecting. A fixed box ignores drag/move/resize while
remaining clickable; a drag on it starts a new box, just like `app_force_draw`.

Editing actions (`app_del`, `app_save`, `app_undo`, `app_redo`, `app_ch_box`,
`app_fix_box`) do nothing in read-only mode; navigation, `app_drop` and
`app_show_hide` still work.

`Alt+1`…`Alt+9` toggles the tag at that 1-based position in `tags.yaml`; it is
built in, not an `app_*` action.

Only `Tab` and the two `Esc` roles (plus popup/menu closing) are handled
specially while typing in inputs; all other shortcuts are ignored while an
input/select is focused. Modifiers are `Ctrl`, `Alt`, `Shift`, `Meta` joined
with `+`.

## Files and folders

The app is split into a relocatable **code folder** and your **user folder**:

```
<root>/
├── .venv/                    virtual environment (created by ybx.sh)
├── actions/ hooks/ filters/ scripts/ shortcuts.txt   your files
├── .recent_data_yamls.json .view_state.json          your app state
└── app/                      the shipped app (replaced on upgrade)
    ├── app.py static/ templates/ requirements.txt VERSION
    └── actions/ hooks/ filters/ scripts/ shortcuts.txt   built-ins
```

The user folder is `--home <dir>`, else the `YBX_HOME` environment variable,
else **the parent of `app.py`**. Because the code lives in `app/`, that parent
is the repo root in a clone and the install root in an installed copy — so both
behave the same with no flags. Your files are read after the shipped ones and
win on a name clash. The app creates the folders when they are missing and logs
`[ybe] user dir: …` (override with `--home`).

## Install

The installer is `ybx.sh`. It downloads the latest version, sets up an isolated
`.venv` and adds a `yolo-box-editor` command to `~/.local/bin`. It works straight
from the internet (no clone needed) or from a checkout:

```bash
# one-liner; installs to ~/.local/share/yolo-box-editor
curl -fsSL https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.sh | bash -s -- install

# or from a clone (offline, uses this checkout):
git clone git@github.com:tabebqena/yolo-box-editor.git
cd yolo-box-editor
./ybx.sh install --from .
```

Common commands:

```bash
ybx.sh version                     # print the installed version
ybx.sh check-update                # 3 lines; exit 0 = update available, 1 = current
ybx.sh upgrade                     # update the app, keeping your files and venv
ybx.sh install --dir ~/ybx --no-link
```

`ybx.sh` only ever replaces `<dir>/app/` (atomically); your `actions/`, `hooks/`,
`filters/`, `scripts/`, `shortcuts.txt` and the `.venv` are never touched. It
picks the latest GitHub release, else the newest tag, else the `main` branch
(override with `--version <tag|branch|commit>`).

Then run the app:

```bash
yolo-box-editor --data /path/to/data.yaml
```

## Run

If you prefer to manage Python yourself, `pip install -r app/requirements.txt`
and run `python app/app.py`:

```bash
python app/app.py --data /path/to/data.yaml
python app/app.py --data /path/to/data.yaml --readonly   # viewer only
python app/app.py --data /path/to/data.yaml --debug      # verbose browser console
python app/app.py --no-resume                            # settings screen, no auto-open
python app/app.py --data /path/to/data.yaml --keep-pipe  # keep each run's {PIPE_PATH} file
python app/app.py --data /path/to/data.yaml --keep-filter-pipes  # keep filter-chain pipe files
python app/app.py --data /path/to/data.yaml --home ./my-user-files  # custom user folder
```

Open <http://127.0.0.1:5000>. You can also leave out `--data` and paste the
`data.yaml` path into the **Settings** dialog (the gear button), then click
*Load data.yaml* — or just run `python app/app.py`, which reopens the dataset you
used last (add `--no-resume` to start with the Settings dialog instead). The
dataset, split, filter chain, last image and view switches are all restored, so
the app comes back as you left it.

`--debug` writes verbose messages to the **browser console** (prefixed `[ybe]`):
the loaded config, image loads, saves, tag writes, user actions / `after_success`
chains, hook runs, rescans and box edits. It also surfaces uncaught errors and
unhandled promise rejections. It is reported to the UI through `/api/config`
(`debug:`), so no server restart is needed to see the flag reflected on reload.

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

Each action is one YAML file in your `actions/` folder (inside your user folder),
shown as a button in the right-hand panel. The action's name is its top-level `name:` key,
or the file name without extension when omitted. A shipped `actions/example.yaml`
template is ignored until you give it steps.

```yaml
# <home>/actions/Remove.yaml — your own action, never overwritten by an upgrade
steps:                  # one entry per line; stop on the first failure
  - rm -f {IMAGE_PATH}  # do NOT put quotes around {PLACEHOLDERS}; the app
  - rm -f {LABEL_PATH}  # shell-quotes them for you
after_success:          # app actions to run, one after another
  - app_refresh_images_list
```

```yaml
# <home>/actions/EditImage.yaml — name: is optional; here it defaults to "EditImage"
name: EditImage
steps:
  - gimp {IMAGE_PATH}   # open the image in an external editor
  - app_refresh_image   # run an app action from `steps` too, then continue
after_success:
  - app_refresh_image   # reload the file you just edited, no full refresh
```

`steps` and `after_success` share one syntax; each entry is one of:

- **an `app_*` name** — a built-in app action, run in the browser (see the table
  below);
- **a `backend_*` name** — a built-in server-side action, run inline by the
  backend (no browser needed). Currently `backend_rescan_images` re-scans the
  image folders and re-applies the active filter chain;
- **`action_<Name>`** — run another action inline, right here, with its own
  `steps` / `after_success` (the prefix keeps a reference from looking like a
  shell command);
- **anything else** — a shell command, run with the placeholders substituted and
  quoted. stdout / stderr / exit code are shown in the popup.

An unknown `app_*` / `backend_*` / `action_*` name is an error. The run is a
single ordered queue and stops at the first failure (the remaining entries are
skipped and the error is reported).

Placeholders (leave them unquoted):

| Placeholder       | Value                                                        |
| ----------------- | ------------------------------------------------------------ |
| `{IMAGE_PATH}`    | path of the current image                                    |
| `{LABEL_PATH}`    | path of the current image's label file (may not exist yet)   |
| `{DATASET_PATH}`  | root path of the loaded dataset                              |
| `{DATA_YAML_PATH}`| path of the loaded data.yaml                                 |
| `{IMAGE_INDEX}`   | 1-based position of the current image (matches the counter)  |
| `{APP_DIR}`       | shipped code folder (use it to reach `{APP_DIR}/scripts/…`)  |
| `{HOME_DIR}`      | your user folder (the working directory of every run)        |
| `{APP_SCRIPT_DIR}`| shipped helper scripts (`app/scripts/`)                      |
| `{USER_SCRIPT_DIR}`| your helper scripts (`<home>/scripts/`)                     |
| `{PIPE_PATH}`     | path of the run's scratch file (see below; may be empty if the temp file could not be created) |

Reach a script **explicitly** with `{USER_SCRIPT_DIR}/helper.py` (yours) or
`{APP_SCRIPT_DIR}/helper.py` (shipped). Because every step runs with the working
directory set to `{HOME_DIR}` (logged to the server console before each command),
`scripts/helper.py` also works **relatively** for your own scripts. The same
paths are exported to each command as `YBE_HOME`, `YBE_APP_DIR`,
`YBE_USER_SCRIPT_DIR` and `YBE_APP_SCRIPT_DIR`.

`{PIPE_PATH}` is a per-run scratch file: it starts empty and every step of the
run — plus every action reached through `after_success` — shares the same file,
so steps can hand data to each other (e.g. `printf '%s\n' {IMAGE_PATH} > {PIPE_PATH}`,
then a later step or chained action reads it back). The backend owns the run, so
it deletes the file when the whole chain (steps + `after_success`) has finished,
whether it succeeded or failed. Pass `--keep-pipe` to keep the file instead,
e.g. for debugging.

Your actions live in `<home>/actions/` and are read after the shipped
`app/actions/`, so a file with the same name wins (matched by action name, so a
`name:` key can retarget an override). App upgrades replace only `app/`, so your
files are never touched. A file with neither `steps` nor `after_success` is
ignored — `app/actions/example.yaml` is such a template.

Helper programs called by those steps live in your `<home>/scripts/` folder:
call them explicitly as `{USER_SCRIPT_DIR}/helper.py`, or relatively as
`scripts/helper.py` (the run's working directory is your user folder). The
shipped `app/scripts/example.py` is a comments-only template, reached as
`{APP_SCRIPT_DIR}/example.py`. The app does not scan either folder — a script
runs only when a `steps` command names it.

`after_success` uses the same entries as `steps` (see above) and runs after them.
The backend drives the whole run: it executes the server-side entries itself and
pauses only when it reaches a client-side `app_*` entry, which it hands to the UI
and waits for before continuing — so a mixed list keeps its exact order. On an
error the run stops, the message is shown and logged to the browser console. The
run is a single queue, so an action can chain into another action from either
list; a cascade is capped at 8 actions per run. Useful app actions:

- `app_refresh_images_list` — re-scan the image folders; the current image is
  kept **by path**, not by index, so the display survives list changes from an
  action (`Archive`) or a re-applied filter chain. When that image was removed, the
  next one that followed it and still exists is shown (clamped at the end).
- `app_reload_images_list` — re-read the server's list *without* a disk scan:
  use it after `backend_rescan_images` so the rescan runs once, server-side.
- `app_refresh_image` — re-fetch the current image from disk (cache-busted),
  e.g. after an external editor saved a new version. Image responses are served
  with `Cache-Control: no-store`, so you never see a stale frame.

An action that changes files (e.g. `Archive`) should rescan server-side and then
reload the UI, so the removal is guaranteed even if the browser is slow:

```yaml
after_success:
  - backend_rescan_images     # server re-scans + re-applies the filter chain, inline
  - app_reload_images_list    # UI re-reads the fresh list (no second scan)
  - app_refresh_image
```

The active split and filter chain are remembered **per dataset** (in
`.view_state.json`, in your user folder), so restarting the server (e.g. the Flask
`--debug` reloader) reopens the dataset in the same view instead of falling back
to *All splits* — that also keeps an open browser tab and the server agreeing on
what an image reference means.

Event hooks (`on_*`) cannot be **referenced** as actions (they are event-driven
only); a bare `on_*` entry is just a shell command. Entries take no arguments.

## Hooks

An **event hook** is a YAML file in your `hooks/` folder (not `actions/`) that
runs when the app fires an event, instead of a toolbar button. Hooks use the
same `steps` / `after_success` and the same placeholders as actions; call scripts
explicitly as `python {USER_SCRIPT_DIR}/<name>.py` (yours) or
`python {APP_SCRIPT_DIR}/<name>.py` (shipped), or relatively as
`python scripts/<name>.py` (steps run with the working directory set to your user
folder). A successful hook reports as a **toast** (auto-hides after a few
seconds); a failed hook opens the result **modal**. They are opt-in:
no file, no hook.

The event comes from the **file name**: `on_<event>.yaml`. If the file name does
not name a known event, the top-level `event_name:` key is used as a fallback.
A file that defines `steps` but names no known event is reported as an error;
`app/hooks/example.yaml` (a comments-only template) is ignored silently. Set
`active: false` to skip a hook without deleting it. Your hooks live in
`<home>/hooks/`, are read after the shipped ones and win on an event clash.

| Hook file | Fired when |
| --------- | ---------- |
| `on_images_list_loaded.yaml` | the image list is (re)loaded |
| `on_image_loaded.yaml` | an image is opened in the editor |
| `on_prev.yaml` | before navigating to the previous image |
| `on_next.yaml` | before navigating to the next image |
| `on_before_save.yaml` | just before labels are written — a failure **aborts the save** |
| `on_after_save.yaml` | after a successful label write |
| `on_box_created.yaml` | a box was drawn |
| `on_box_deleted.yaml` | a box was removed |
| `on_box_edited.yaml` | a box was moved / resized / reclassed (committed edits) |

```yaml
# <home>/hooks/on_after_save.yaml — run a script after every save
steps:
  - python {USER_SCRIPT_DIR}/helper.py {DATA_YAML_PATH} {IMAGE_PATH} {LABEL_PATH}
```

```yaml
# hooks/after-save-copy.yaml — event_name: fallback when the name does not
# encode an event; active: false would skip it
event_name: after_save
steps:
  - touch {DATASET_PATH}/saved.log
```

Hooks are event-only: they are never shown as buttons and cannot be bound in
`shortcuts.txt` (that is reported as an error). A hook whose `after_success`
refreshes the image list cannot re-trigger itself — re-entrant runs of the same
hook are skipped.

## Tags

YOLO has no canonical tagging scheme, so this app defines a minimal one. It is
opt-in: flip the **Tags** switch in **Settings** to show a tag bar below the image.

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

A **filter** narrows the loaded image list to the images a script returns.
**Filters are chainable**: the `Filters` button in the right-hand panel (below
`Split`) appears once a `data.yaml` is loaded and opens a modal with a stack of
selects (up to 8).
Pick a filter in each select and they run **top to bottom** — each one receives
the previous one's result, applies its own logic, and passes its result on. The
last filter's output is exactly what the app shows (count, Prev/Next, the counter
jump and resume all follow it). `No filter` clears the whole chain.

Each filter is one **Python script** in a `filters/` folder, run as:

```bash
python <filter-script> <data.yaml> <split> <input_pipe> <output_pipe>
```

with the working directory set to your user folder (logged to the server
console). Shipped filters live in `app/filters/`; your filters live in
`<home>/filters/`, are read after the shipped ones and win on a name clash.

- `<data.yaml>` — path of the loaded dataset's `data.yaml`.
- `<split>` — `train` / `val` / `test`, or an empty string when the UI is on
  *All splits* (the filter decides what to return then).
- `<input_pipe>` — a file with the candidate images, one **absolute path** per
  line. The first filter's input is the active split's images (every scanned
  image when the split is *All splits*).
- `<output_pipe>` — the file the filter must write the paths it keeps to, one
  absolute path per line.

The app feeds each output pipe to the next filter and keeps the final images
**in that order** (handy for ranking). Blank lines are ignored and duplicates
are dropped; a path that is not in the dataset is skipped and a notice is shown.
A non-zero exit code or a timeout (120 s) stops the chain — nothing is applied,
so the previous chain (if any) stays in effect, and the failing filter is named
in the message. The scratch pipe files are deleted after each run; pass
`--keep-filter-pipes` to keep them for debugging.

The chain re-runs when you apply it, when you change the split (while one is
active), and after an image-list rescan. The image you are on is tracked by its
path, so re-applying a chain keeps you on it when it is still in the result
(otherwise you are moved to the nearest surviving image). The active chain is
remembered in your browser and restored when you reopen the app — even after a
server restart.

Your filters live in `<home>/filters/` (read after the shipped `app/filters/`,
win on a name clash). `app/filters/example.py` is a comments-only template
documenting the contract.

## Development

A single Flask module (`app/app.py`) with a hand-rolled `data.yaml` parser (no
PyYAML needed to run). The UI is `app/templates/index.html` + `app/static/app.js`
+ `app/static/style.css` and needs no build step.

Behaviour checks live in `tests/` and are run from the repo root:

```bash
python -m pytest -q
```

See also: [TUTORIAL.md](TUTORIAL.md), [CHANGELOG.md](CHANGELOG.md),
`VERSION`, `LICENSE`.
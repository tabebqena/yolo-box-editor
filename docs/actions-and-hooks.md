# Actions and hooks

Actions are custom commands you run on the current image from a button (with a
confirmation). Hooks are the same kind of command, but they run automatically on
an app event instead of a button.

## Create actions and hooks in the web UI

**Settings → Actions** and **Settings → Hooks** build the YAML for you, so you
never have to get the indentation or the `:` / `-` right by hand. Each has two
sub-tabs, **Create** and **Existing**:

- On **Create**, type a name (actions) or pick an event (hooks), then fill
  **Steps** and **After success**. An entry can be a shell command, an `app_*` /
  `backend_*` built-in, or another `action_<Name>` — choose the type from the
  dropdown.
- **Insert placeholder** buttons drop a token such as `{IMAGE_PATH}` into the
  command at the cursor, so you do not have to remember the spelling.
- On **Existing**, your files are listed and can be deleted there; shipped
  files are never deleted.
- Each existing action/hook also has an **Enabled for this dataset** checkbox.
  Uncheck it to disable the extension for the loaded `data.yaml` only — the file
  is left untouched, the toolbar button disappears and the hook stops firing (a
  disabled action also cannot be run as an `action_<Name>` reference). The
  choice is remembered per dataset and can be reverted at any time.

Every extension file carries an `api_version` (currently `1`). A file whose
version is missing or older than the app is shown as **outdated**: use its
**YAML** button to open it in the raw editor, adjust it and save — the version
is bumped for you and comments are kept. A file **newer** than the app is
blocked with a warning. Files without `api_version` still load.

## Built-in app actions

The built-in app actions are defined in `app/app.py` (`APP_ACTIONS`) and
implemented in `app/static/app.js`. Rebind them from **Settings → Shortcuts →
Edit** (or by hand in your `shortcuts.txt`); the names themselves are fixed.
They are also the valid values for an action's `after_success` — they are
**not** valid in `steps` (those are shell commands or `action_<Name>`
references).

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
| `app_show_hide` | `.` | toggle the box overlay (hidden boxes ignore the mouse) |
| `app_box_details` | `,` | toggle the box handles, class label and `x` / `/` buttons (outlines only) |
| `app_fix_box` | `F` | fix / unfix the selected box (transient: never saved) |
| `app_force_draw` | `Ctrl` | held modifier: hold it and drag to always draw a new box |
| `app_refresh_images_list` | — | re-scan the image folders; stay on the same image by path |
| `app_reload_images_list` | — | re-read the server list **without** re-scanning the disk |
| `app_refresh_image` | — | re-fetch the current image (cache-busted) |
| `app_help` | `F1` | open the built-in help (tutorial + How to?) |
| `app_select_next_box` | — | select the next box (same as `app_sel_box`, callable from a step) |
| `app_select_prev_box` | — | select the previous box |
| `app_clear_tags` | — | remove every tag from the current image |
| `app_copy_labels_from_prev` | — | copy the previous image's boxes and tags onto the current one |

The four actions at the end are meant to be called from an action/hook `steps`
or `after_success` rather than bound to a key; they have no default key.

`app_force_draw` is special: its binding is a *modifier* (`Ctrl`, `Alt`,
`Shift`, `Meta`, or a `+`-joined combination), not a key.

Editing actions (`app_del`, `app_save`, `app_undo`, `app_redo`, `app_ch_box`,
`app_fix_box`, `app_clear_tags`, `app_copy_labels_from_prev`) do nothing in
read-only mode; navigation, `app_drop` and `app_show_hide` still work.

## User actions

Each action is one YAML file in your `actions/` folder, shown as a button in the
right column. The action's name is its top-level `name:` key, or the file name
without extension when omitted. A shipped `actions/example.yaml` template is
ignored until you give it steps.

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

- **an `app_*` name** — a built-in app action, run in the browser;
- **a `backend_*` name** — a built-in server-side action, run inline by the
  backend (no browser needed). Currently `backend_rescan_images` re-scans the
  image folders and re-applies the active filter chain;
- **`action_<Name>`** — run another action inline, right here, with its own
  `steps` / `after_success`;
- **anything else** — a shell command, run with the placeholders substituted and
  quoted. stdout / stderr / exit code are shown in the popup.

An unknown `app_*` / `backend_*` / `action_*` name is an error. The run is a
single ordered queue and stops at the first failure.

### Placeholders

Leave them unquoted; the app shell-quotes each value for you.

| Placeholder | Value |
| ----------- | ----- |
| `{IMAGE_PATH}` | path of the current image |
| `{LABEL_PATH}` | path of the current image's label file (may not exist yet) |
| `{TAGS_DIR}` | tags folder for the current image's split (honours a custom tags dir) |
| `{DATASET_PATH}` | root path of the loaded dataset |
| `{DATA_YAML_PATH}` | path of the loaded data.yaml |
| `{IMAGE_INDEX}` | 1-based position of the current image (matches the counter) |
| `{APP_DIR}` | shipped code folder (reach `{APP_DIR}/scripts/…`) |
| `{HOME_DIR}` | your user folder (the working directory of every run) |
| `{APP_SCRIPT_DIR}` | shipped helper scripts (`app/scripts/`) |
| `{USER_SCRIPT_DIR}` | your helper scripts (`<home>/scripts/`) |
| `{PYTHON}` | the Python interpreter running the app (`sys.executable`) |
| `{PIPE_PATH}` | path of the run's scratch file (may be empty) |

Reach a script **explicitly** with `{USER_SCRIPT_DIR}/helper.py` (yours) or
`{APP_SCRIPT_DIR}/helper.py` (shipped). Start a Python step with `{PYTHON}`
rather than `python`, which may not be on `PATH`. Because every step runs with
the working directory set to `{HOME_DIR}`, `scripts/helper.py` also works
**relatively** for your own scripts. The same paths are exported to each command
as `YBE_HOME`, `YBE_APP_DIR`, `YBE_USER_SCRIPT_DIR` and `YBE_APP_SCRIPT_DIR`.

`{PIPE_PATH}` is a per-run scratch file shared by every step and every action
reached through `after_success`, so steps can hand data to each other. It is
deleted when the whole chain finishes; pass `--keep-pipe` to keep it.

Helper programs live in your `<home>/scripts/` folder: call them explicitly as
`{USER_SCRIPT_DIR}/helper.py`, or relatively as `scripts/helper.py`. The shipped
`app/scripts/example.py` is a comments-only template. The app does not scan
either folder — a script runs only when a `steps` command names it.

An action that changes files (e.g. `Archive`) should rescan server-side and then
reload the UI:

```yaml
after_success:
  - backend_rescan_images     # server re-scans + re-applies the filter chain
  - app_reload_images_list    # UI re-reads the fresh list (no second scan)
  - app_refresh_image
```

## Hooks

An **event hook** is a YAML file in your `hooks/` folder (not `actions/`) that
runs when the app fires an event. Hooks use the same `steps` / `after_success`
and placeholders as actions. Running an action or hook is silent when it
succeeds (the result is logged to the browser console); only a failure shows a
**toast**. They are opt-in: no file, no hook.

The event comes from the **file name**: `on_<event>.yaml`. If the file name does
not name a known event, the top-level `event_name:` key is used as a fallback.
A file that defines `steps` but names no known event is reported as an error.
Set `active: false` to skip a hook for **every** dataset without deleting it, or
uncheck **Enabled for this dataset** in Settings → Hooks to skip it for the
loaded dataset only (see above). Your hooks live in `<home>/hooks/`, are read
after the shipped ones and win on an event clash.

| Hook file | Fired when |
| --------- | ---------- |
| `on_images_list_loaded.yaml` | the image list is (re)loaded |
| `on_image_loaded.yaml` | an image is opened in the editor |
| `on_before_prev.yaml` | before leaving to the previous image, before the unsaved-changes / auto-save handling |
| `on_before_next.yaml` | before leaving to the next image, before the unsaved-changes / auto-save handling |
| `on_prev.yaml` | before navigating to the previous image |
| `on_next.yaml` | before navigating to the next image |
| `on_before_save.yaml` | just before labels are written — a failure **aborts the save** |
| `on_after_save.yaml` | after a successful label write |
| `on_box_created.yaml` | a box was drawn |
| `on_box_deleted.yaml` | a box was removed |
| `on_box_edited.yaml` | a box was moved / resized / reclassed |

```yaml
# <home>/hooks/on_after_save.yaml — run a script after every save
steps:
  - python {USER_SCRIPT_DIR}/helper.py {DATA_YAML_PATH} {IMAGE_PATH} {LABEL_PATH}
```

Hooks are event-only: they are never shown as buttons and cannot be bound in
`shortcuts.txt`. A hook whose `after_success` refreshes the image list cannot
re-trigger itself — re-entrant runs of the same hook are skipped.

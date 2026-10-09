# Filters

A **filter** narrows the loaded image list to the images its script returns.
**Filters are chainable**: open **Settings** (⚙) and use the **Filters** tab. It
has three sub-tabs — **Active chain**, **Create** and **Library**. The **Active
chain** sub-tab stacks up to **8** selectors; use **+ Add filter** to add a row
and the **×** on a row to remove it (the last row stays). Pick a filter in each
selector and they run **top to bottom** — each one receives the previous one's
result, applies its own logic, and passes its result on. The last filter's output
is exactly what the app shows (count, Prev/Next, the counter jump and resume all
follow it). **Apply** runs the chain (a spinner shows while it works) and closes
Settings when it finishes; `No filter` clears the whole chain.

Each filter is defined by **one YAML file** in a `filters/` folder. Shipped
filters live in `app/filters/`; your filters live in `<home>/filters/`, are read
after the shipped ones and win on a name clash.

## Create a filter in the web UI

**Settings → Filters → Create** has the **Create a filter** form (below the chain,
in its own sub-tab). Give the filter a name, an optional description, any
arguments (name / required / default / comma-separated options) and its **Steps**.
Each command row has **Insert placeholder** buttons (`{INPUT_PIPE}`,
`{OUTPUT_PIPE}`, `{SPLIT}`, every argument's `{NAME}`, …), so you never type a
token from memory. Your filters are listed in the **Library** sub-tab under
**Existing** and can be deleted there; shipped ones cannot.

Every filter file carries an `api_version` (currently `4`). A missing or older
version is shown as **outdated** and can be opened in a raw YAML editor with its
**YAML** button; saving bumps the version and keeps comments. A file **newer**
than the app is blocked with a warning. Files without `api_version` still load.

## Format

```yaml
name: Sharp only            # optional; defaults to the file name
description: Keep sharp images (shown in the Filters tab, trimmed)
active: true                # optional; false hides the filter everywhere
arguments:                  # optional list of dicts
  - name: threshold         # -> the in-place placeholder {THRESHOLD}
    required: true          # a required argument must have a value
    default: "100"          # pre-filled value
    options: ["50", "100", "200"]   # inline list -> a dropdown
  - name: invert
    default: "false"
    options: ["false", "true"]
steps:                      # one shell command per entry, run in order
  - {PYTHON} {USER_SCRIPT_DIR}/sharp.py {DATA_YAML_PATH} {SPLIT} {INPUT_PIPE} {OUTPUT_PIPE} --threshold {THRESHOLD} --invert {INVERT}
```

- `name` wins the filter name; without it the file name (minus `.yaml`) is used.
- `active: false` is an app-global off switch: the filter does not appear in the
  UI and cannot be selected (a saved chain that used it drops that step).
- An argument with `options` is shown as a dropdown and the app rejects a value
  that is not one of them. Besides literal lists, the token
  `{DATASET_CLASS_NAMES}` expands to the loaded dataset's class names, so a
  class filter can never be given a typo'd class. Other dynamic tokens may be
  added later.
- A filter with no `steps` (e.g. a comments-only template you copied) is
  ignored.
- An argument name must be letters, digits and `_` (not starting with a digit)
  and must not shadow a placeholder below. A bad name, a collision, or a
  duplicate drops the whole filter and shows an error in the UI.

## Steps and placeholders

`steps` is a list of shell commands. There is no `after_success`. Every step
gets the same values substituted (and shell-quoted) as an action step, plus the
pipe paths and each argument:

| Placeholder | Value |
| --- | --- |
| `{DATA_YAML_PATH}` | path of the loaded `data.yaml` |
| `{DATASET_PATH}` | root path of the loaded dataset |
| `{SPLIT}` | `train` / `val` / `test`, or `""` on *All splits* |
| `{INPUT_PIPE}` | file with the candidate image paths, one absolute path per line |
| `{OUTPUT_PIPE}` | file the filter must write the kept image paths to |
| `{APP_DIR}` | the folder holding `app.py` (the shipped code) |
| `{HOME_DIR}` | your user folder (the working directory of every run) |
| `{APP_SCRIPT_DIR}` | the shipped helper scripts (`app/scripts/`) |
| `{USER_SCRIPT_DIR}` | your helper scripts (`<home>/scripts/`) |
| `{PYTHON}` | the Python interpreter running the app (`sys.executable`) |
| `{<ARG>}` | each declared argument, upper-cased (`threshold` -> `{THRESHOLD}`) |

Write your filter logic as a helper script under `<home>/scripts/` (shipped
examples live in `app/scripts/`) and call it from `steps`, e.g.
`{PYTHON} {USER_SCRIPT_DIR}/sharp.py {INPUT_PIPE} {OUTPUT_PIPE} {THRESHOLD}`.
Always start a Python step with `{PYTHON}` rather than `python`: it is the
interpreter already running the app, so it works even when `python` is not on the
`PATH`. Export the values yourself with `--threshold {THRESHOLD}` if the script
prefers flags. Because steps run with the working directory set to `{HOME_DIR}`,
`scripts/sharp.py` also works relatively.

## The pipes

The first filter's input is the active split's images (every scanned image when
the split is *All splits*); each later filter gets the previous filter's output.
The filter reads candidate absolute paths from `{INPUT_PIPE}` and writes the
paths it keeps to `{OUTPUT_PIPE}`, one per line. All steps of one filter share
the same input/output pipes.

The app keeps the final images **in that order** (handy for ranking). Blank
lines are ignored and duplicates are dropped; a path that is not in the dataset
is skipped and a notice is shown. A non-zero exit code or a timeout (120 s)
stops the chain — nothing is applied, so the previous chain (if any) stays in
effect, and the failing filter is named. The scratch pipe files are deleted
after each run; pass `--keep-filter-pipes` to keep them for debugging.

## Lifecycle

The chain re-runs when you apply it, when you change the split (while one is
active), and after an image-list rescan. The image you are on is tracked by its
path, so re-applying a chain keeps you on it when it is still in the result
(otherwise you are moved to the nearest surviving image). The active chain,
including the argument values you entered, is remembered per dataset and
restored when you reopen the app — even after a server restart.

`app/filters/example.yaml` is a working example (`Keep every N-th (example)`)
backed by `app/scripts/example_filter.py`; copy it to a new `<Name>.yaml` in
`<home>/filters/` to start your own.

## Shipped filters

- **Keep every N-th (example)** — `app/filters/example.yaml`; keeps one image
  out of every N, optionally reversed.
- **Contains class** — `app/filters/contains_class.yaml`; keeps only the images
  whose label contains the chosen class. The class is picked from a dropdown
  built from the dataset's `names` (`options: {DATASET_CLASS_NAMES}`).
- **Does not contain class** — `app/filters/not_contains_class.yaml`; the
  inverse.

Both class filters use `app/scripts/class_filter.py`, which maps the class name
to its id via `data.yaml` and checks each image's `labels/.../*.txt` file (an
image with no label file contains no class).

The **Has tag** / **Does not have tag** filters ship with the tags extension
package (`app/extensions/tags/filters/`); enable it under **Settings →
Extensions** to use them. They use
`app/extensions/tags/scripts/tag_filter.py`, which checks each image's tag file
(found by swapping the last `images` segment for `tags`, or the dataset's custom
tags folder); an image with no tag file has no tags.

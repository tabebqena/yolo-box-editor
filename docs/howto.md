# How to?

Task-focused recipes for yolo-box-editor. The same guide is built into the app:
press **F1** (or click **?** in the top panel) and open the **How to?** tab.

Deeper reference lives in the other docs:
[install](install.md) · [dataset](dataset.md) · [tags](tags.md) ·
[filters](filters.md) · [actions and hooks](actions-and-hooks.md).

## Install and start

```sh
# one-liner (needs Python 3)
curl -fsSL https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.sh | sh -s -- install

# start with a dataset, then open http://127.0.0.1:5000
ybe start --data /path/to/data.yaml
```

From a clone: `python app/app.py --data /path/to/data.yaml`. Already running?
Use `ybe status`, `ybe logs -f`, `ybe stop`.

## Load or switch a dataset

Open **⚙ Settings → Dataset**, paste the path to `data.yaml` and click
**Load** (or pick a **Recent…** entry). On a first run the load box appears by
itself. See [dataset, files and formats](dataset.md).

## Draw a box

Drag from one corner of the object to the opposite one, then click the class in
the pop-up (or press its number). To draw inside an existing box, hold `Ctrl`
and drag.

## Move or resize a box

Click the box to select it, then drag inside it to move, or drag one of its
eight handles to resize. For exact values, type into `cx`, `cy`, `w` or `h` in
its row in the Boxes list.

## Delete a box

Select it and press `Delete` or `Backspace`, or click the **×** in its row.

## Change a box's class

Select the box, press `/` (or click the **/** on the box), then choose the new
class.

## Undo a mistake

`Z` undoes the last edit to the current image; `Y` redoes it. Press `Esc` right
after drawing to drop the box you just made.

## Save my work / find the label files

Press `S` or click **Save**. Labels are written to
`labels/<split>/<image>.txt`, five numbers per line. Turn on **Auto-save** in
**Settings → General** to save after every edit.

## Tag an image

Click a tag badge to toggle it; click **+** to create a new tag. Use
`Alt+1`…`Alt+9` for the numbered tags. Available tags come from `tags.yaml` —
see [tags](tags.md).

## Show only some images

**Settings → Filters → Active chain**: add up to 8 filters, set their
arguments, and click **Apply**. See [filters](filters.md).

## Rearrange the panels

**Settings → Layout**: move the control panel left/right, and show, hide, float
or dock each widget. Drag a panel divider to resize it.

## Create an action (custom button)

**Settings → Actions → Create**: name it, add one command per step using the
**Insert placeholder** buttons, and save. See
[actions and hooks](actions-and-hooks.md).

## Create a filter

**Settings → Filters → Create**: give it a name, arguments and steps that read
`{INPUT_PIPE}` and write `{OUTPUT_PIPE}`. Copy `app/filters/example.yaml` as a
starting point.

## Create a hook (run on an event)

**Settings → Hooks → Create**: pick an event such as *after_save* and add
steps. The file is `hooks/on_after_save.yaml`. See
[actions and hooks](actions-and-hooks.md#hooks).

## Change a keyboard shortcut

**Settings → Shortcuts → Edit**: click the binding, press the new keys, then
**Save**. **↺** resets one to the default. You can also edit your
`shortcuts.txt` by hand.

## Browse without changing anything

Tick **Read-only** in **Settings → General**, or start with `--readonly`.
Drawing, editing, tags and saving are blocked.

## Update or uninstall

```sh
ybe update      # update in place, keeping your files
ybe uninstall   # remove the app, keeping your files
```

See [install, update and run](install.md).

## Nothing shows up / something looks wrong

- **No dataset** — load a `data.yaml` (**Settings → Dataset**).
- **No images** — check the split, then click the reload (↻) button beside the
  Split picker.
- **A tag is missing** — it must be listed in `tags.yaml` beside `data.yaml`.
- **Boxes on top / tiny numbers** — coordinates are fractions of the image, so
  small images make chunky values; that is normal.
- **A command failed** — the action pop-up shows its output, error and exit
  code; check the path and the placeholders.

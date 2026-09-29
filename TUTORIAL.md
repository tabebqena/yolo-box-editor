# yolo-box-editor — beginner tutorial

A walkthrough for labelling your first images. You will learn: how to start the
app, load a dataset, draw and fix boxes, and save your work.

## 1. What you are building

The app lets you draw rectangles around objects (fires, smoke, cars, birds…)
in images. Each rectangle is a **box**, and boxes are saved to disk in **YOLO
format** — one short text line per box, ready to feed to a YOLO training script.

A single box is written as five numbers:

```
<class_id> <x_center> <y_center> <width> <height>
```

- `class_id` — which kind of object it is (`0` = first name in `data.yaml`).
- the next four are **normalized** coordinates: fractions of the image width or
  height, from `0.0` (left/top edge) to `1.0` (right/bottom edge).

You do not type these numbers yourself — you draw rectangles and the app writes
the numbers.

## 2. Fields and folders

Your dataset is a folder tree like this:

```
dataset/
├── data.yaml
├── images/
│   ├── train/     ← photos to label
│   ├── val/
│   └── test/
└── labels/
    ├── train/     ← the app writes labels here
    ├── val/
    └── test/
```

`data.yaml` tells the app which folders are which and what your class names are:

```yaml
path: dataset            # optional; default = the folder with data.yaml
train: images/train
val: images/val
test: images/test

nc: 3
names: ['fire', 'smoke', 'other']
```

`labels/` is optional to create — the app makes it for you the first time you
save.

## 3. Start the app

The easy way is the installer (no clone needed):

```bash
curl -fsSL https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.sh | bash -s -- install
yolo-box-editor --data /path/to/dataset/data.yaml
```

Or run it straight from a clone:

```bash
git clone git@github.com:tabebqena/yolo-box-editor.git
cd yolo-box-editor
python app/app.py --data /path/to/dataset/data.yaml
```

Open <http://127.0.0.1:5000>. You should see your first image and an empty
canvas.

> Prefer pointing mouse only? Just run `python app/app.py` — it reopens the dataset
> you used last, so you land right back where you left off. On a first run (or
> with `--no-resume`) the **Settings** dialog opens: paste the `data.yaml` path
> and click **Load data.yaml**. Reopen it any time with the **⚙ Settings** button
> (top right) to switch datasets or change view options.

## 4. The screen at a glance

- **Right column** — everything except the image, top to bottom: the app label
  with the **⚙ Settings**, notifications bell and **Panel** toggle; the dataset
  name; separators; the _Split_ picker; the applied _Filter_ names with a `…`
  button that opens the filter modal; the per-dataset action buttons (a few,
  with a `…` to show the rest); and finally the _Boxes_ list for the current
  image (one row per box with its class dropdown, `cx cy w h` number inputs and
  a `×`). The column width can be dragged from its left edge. The **Panel**
  toggle collapses the whole column (the image takes the full width); only the
  **Panel** and bell buttons remain, floating over the top-right corner.
- **Middle** — the picture (canvas).
- **Bottom bar** — one row with the tag controls (when Tags is on) plus image
  navigation (Prev / Next, counter) and Undo / Redo / Save.
- **Settings** (⚙) — the _Read-only_, _Tags_ and _Auto-save_ switches, the
  dataset field and a **Show all shortcuts** button opening the full shortcut list.

## 5. Your first box

1. **Drag** on the image from the top-left corner of the object to its
   bottom-right corner. A rectangle follows your mouse.
2. When you release, a **class list** pops up — click the class of the object
   (or press its number). Done: a green box with the class label appears.

The new box is automatically *selected*: it is yellow on the canvas, and its row
in the right panel is **active** (controls enabled).

> **Drawing on top of an existing box?** A normal drag inside a box grabs and
> moves that box. Hold the force-draw modifier (default **`Ctrl`**) and drag to
> draw a brand-new box regardless of what is under the cursor. The modifier is
> configurable via `app_force_draw` in `shortcuts.txt`.

## 6. Selecting a box

A box is *selected* in any of these ways:

- **click it** on the canvas (it turns yellow with 8 handles),
- **click its row** in the side panel — any of the row's controls, the row
  background, or the `×`, all work,
- press **`Shift`** to jump to the next box (and after `Esc` it resumes from
  the box that was active before).

Only the selected box's row has usable controls; every other row is greyed out.
Selecting a different box deactivates the previous one. Press **`Esc`** to
deselect everything.

## 7. Editing boxes

### On the canvas

- **Move** it: click inside the selected box and drag.
- **Resize** it: drag any of the 8 handles (corners and edges).
- **Change class**: click the `/` on the box, or press `/`.
- **Delete** it: press `Delete`/`Backspace`, or click its `×` in the panel.
- **Fix / unfix** it: press `F`, or click the `F` button in its row. A *fixed*
  box is drawn with a dashed grey outline and no handles: it ignores dragging
  (moving and resizing) but can still be clicked, selected and deleted. This is
  handy to protect a finished box while you draw inside it. Fixing is transient
  — it is **not saved** and is cleared as soon as you change image.

### With the keyboard (row editing)

Select a box, then press **`Tab`**. Focus jumps into its row and `Tab` then
cycles class select → `cx` → `cy` → `w` → `h` → class select…, so you can edit
every value without touching the mouse. While a coordinate input is focused,
the canvas highlights that value in orange so you can see exactly what you are
changing:

- `cx` / `cy` — an orange dot at the box centre (the point you're moving);
- `w` — orange dashes on the box's left and right edges;
- `h` — orange dashes on its top and bottom edges.

Press **`Esc`** to leave the row (deactivates it and clears the orange
highlight).

### Typing coordinates

Click the selected row's `cx`, `cy`, `w` or `h` field and type a value. The box
moves/resizes on the canvas as you type. Values are kept inside `0..1`.

> Coordinates are fractions, so `cx 0.5 / cy 0.5` is the centre of the image and
> `w 0.25` is a box a quarter of the image wide. On small images these numbers
> feel chunky — that is normal.

## 8. Undo, redo and save

- **Undo** `z` / **Redo** `y` revert box edits *for the current image* one step
  at a time.
- **Save** `s` writes all boxes of the current image to
  `labels/<split>/<image-name>.txt` (e.g. `labels/train/photo_01.txt`). The
  **Save** button is active only when the image has unsaved changes.

Use `→` / `←` (or **Prev / Next**) to move between images. Unsaved boxes are
kept in the app's memory for the session — but **save before switching images**
to survive a refresh.

## 9. Read-only mode

To browse without any chance of damaging labels, tick **Read-only** in
**Settings** (or start with `python app/app.py --data … --readonly`). Drawing,
editing and saving stop working; boxes still display.

## 10. Tags (optional)

Tags are short labels you attach to a whole image (not to a box) — useful to
mark, say, "night", "indoor" or "hard". They are separate from YOLO classes.

1. Tick **Tags** in **Settings** to show the tag controls in the bottom bar.
2. The dataset's tags appear as **badges**. Green = the tag is on this image;
   grey = it is not. **Click a badge** to toggle it — the image's tag file is
   saved straight away.
3. To make a new tag, click the small **+** button to reveal the input, type its
   name and press `Enter` (or click **✓**). New names are also written to
   `tags.yaml`, the dataset's list of available tags, so they reappear for other
   images.
4. **`Alt+1` … `Alt+9`** toggles the 1st, 2nd, … tag from `tags.yaml` — the
   numbers shown on the badges. This also switches tagging on for you.
5. If the badges are wider than the row, a **…** button appears — click it to
   wrap them onto more lines, and click again to collapse.

Tags are stored as one name per line in a `tags/` folder beside `labels/`
(`tags/train/photo_01.txt` for `images/train/photo_01.jpg`). Removing a tag from
an image does **not** remove it from `tags.yaml`.

## 11. Keyboard shortcuts (the whole list)

| Key            | Action                                      |
| -------------- | ------------------------------------------- |
| `→` / `←`      | next / previous image                       |
| `Delete`/`Backsp.` | delete the selected box                  |
| `z` / `y`      | undo / redo                                 |
| `s`            | save labels                                 |
| `/`            | class menu for the selected box             |
| `Shift`        | select the next box (resumes after `Esc`)   |
| `Tab`          | cycle the selected row: class → cx → cy → w → h |
| `Esc`          | drop a just-drawn box, deselect, or deactivate the focused row |
| `.`            | hide / show the box overlay (hidden boxes ignore the mouse) |
| `F`            | fix / unfix the selected box (transient, not saved) |
| `Ctrl`+drag    | force-draw a new box, even inside an existing one |
| `Alt+1`…`Alt+9`| toggle tag by number (from `tags.yaml`)     |

All of these are configurable — edit your `shortcuts.txt` in the user folder (see the
README) if you prefer different keys. The `Alt+1…9` tag toggles are built in.

## 12. When you are done

1. **Save** (`s`) on every image you edited.
2. Check a label file: five numbers per line, all coordinates between `0` and `1`.
3. Train your model!

## Ideas for a real first session

1. New folder with 5 photos; write a 2-class `data.yaml`
   (`names: ['fire', 'smoke']`).
2. Start the app, draw one box per photo, press `s`.
3. On one image, select a box, press `Tab` a few times and tweak `w` — watch the
   orange markers and the box change live.
4. Open one generated `labels/*.txt` — the numbers should match what you drew.

If anything looks wrong (boxes on top, tiny numbers), re-read §6–§8 above.
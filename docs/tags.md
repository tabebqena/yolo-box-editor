# Tags

> Tags ships as an **extension package**. It is enabled by default on a fresh
> install; if you previously hid the tag bar, the update carries that choice
> over. The on/off flag lives in `<home>/extensions.json` and can be changed
> with `app/scripts/migrate_tags_extension.py --disable` / `--enable` (restart
> the app after). Everything below still describes the tag files and the
> behaviour, which are unchanged.

YOLO has no canonical tagging scheme, so this app defines a minimal one. The tag
controls show as a panel; enable the package and show/hide it under
**Settings → Layout**.

![Tag bar: active tags filled, inactive outlined](tags.svg)

## Where tags live

- **`tags.yaml`** lives next to `data.yaml` and holds the dataset's available
  tags. It is **required** — it is the list of tags the bar can offer. It is a
  plain list, one tag per line, each prefixed by `- ` (the format written by
  `dataset_autotag.py`):

  ```yaml
  - fire
  - smoke
  - dangerous
  ```

  A nested `tags:` key is **not** used and is ignored; saving rewrites the file
  as a plain list, so an old `tags:` block is cleaned up.

- **Per-image tags** live in a `tags/` folder beside `images/` and `labels/`.
  By default the folder is derived the same way as labels
  (`images/train` → `tags/train`). Each image `foo.jpg` gets
  `tags/train/foo.txt` with one tag name per line; an empty/absent file means
  "no tags". Override the folder per dataset in **Settings → Dataset → Tags
  folder** (saved with the dataset's view state); leave it empty to use the
  default derivation.

## The tag bar

- Every tag in `tags.yaml` is a clickable badge. A badge is **active** (green)
  when the tag is on the current image and **inactive** (outlined) when it is
  not. Clicking toggles it; the change is written when you save.
- **Add a tag**: click the `+` button, type a name and press `Enter`. The name is
  attached to the image; if it is new it is added to `tags.yaml` on the next
  save (see below).
- **Overflow**: when the badges are wider than the row, a `…` button wraps them
  onto more lines.
- **Keyboard**: `Alt+1` … `Alt+9` toggles the tag at that 1-based position in
  `tags.yaml`. Using the shortcut shows the Tags widget if it was hidden.
- Tag writes are blocked in read-only mode.

## Why can't I see my tag?

The bar only shows the tags in `tags.yaml` plus the current image's own tags. If
a tag seems to be missing:

1. **The tag is not in `tags.yaml`.** A tag that exists only on an image is
   shown as an active badge, with a warning: *"N tag(s) not in tags.yaml — added
   on save"*. Press **Save** and the new names are added to `tags.yaml`, so they
   become normal badges.
2. **There is no `tags.yaml`.** The bar warns *"No tags.yaml found beside
   data.yaml"*. Create `tags.yaml` next to `data.yaml` (or add a tag with `+`
   and save) and it will be used.
3. **The tags folder is not where the app looks.** If your per-image tag files
   live somewhere other than `tags/` beside `images/`, set **Settings → Dataset
   → Tags folder** to that base folder (each split uses a subfolder of it).

## Saving tags

Saving an image writes its labels and tags together. The backend:

- writes the current image's tag file, and
- adds only the **new** tag names to `tags.yaml` — if there is nothing new,
  `tags.yaml` is left untouched.

There is no built-in tag action or hook to configure; the save does it. Tag
edits also join the undo/redo history, so `Z` / `Y` cover them like box edits.

Removing a tag from an image never deletes it from `tags.yaml`.

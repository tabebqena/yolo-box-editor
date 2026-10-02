# Tags

YOLO has no canonical tagging scheme, so this app defines a minimal one. The tag
controls show in the bottom bar by default; show/hide them with the **Tags**
widget in **Settings → Layout**.

![Tag bar: active tags filled, inactive outlined](tags.svg)

## Where tags live

- **`tags.yaml`** lives next to `data.yaml` and holds the dataset's available
  tags. It is **required** — it is the list of tags the bar can offer. Two
  shapes are accepted:

  ```yaml
  tags:
    - fire
    - smoke
    - dangerous
  ```

  or a plain list of names (the `tags:` key is optional):

  ```yaml
  - fire
  - smoke
  - dangerous
  ```

  If a file somehow has both, the two are merged (duplicates removed). On the
  next save the file is rewritten in the canonical `tags:` form, so a plain
  list is never left behind as a second, stale list.

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
  not. Clicking toggles it and writes the image's tag file.
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
   on save"*. Press **Save** and the built-in `update_tags` action adds the new
   names to `tags.yaml`, so they become normal badges.
2. **There is no `tags.yaml`.** The bar warns *"No tags.yaml found beside
   data.yaml"*. Create `tags.yaml` next to `data.yaml` (or add a tag with `+`
   and save) and it will be used.
3. **The tags folder is not where the app looks.** If your per-image tag files
   live somewhere other than `tags/` beside `images/`, set **Settings → Dataset
   → Tags folder** to that base folder (each split uses a subfolder of it).

## update_tags and the after-save hook

The built-in `update_tags` action:

- writes the current image's tag file, and
- appends only the **new** tag names to `tags.yaml` — if there is nothing new,
  `tags.yaml` is left untouched.

It is run automatically after every save by the shipped
`app/hooks/on_after_save.yaml` hook. To turn that off (or replace it), create
your own `<home>/hooks/on_after_save.yaml`:

```yaml
event_name: after_save
active: false
```

Removing a tag from an image never deletes it from `tags.yaml`.

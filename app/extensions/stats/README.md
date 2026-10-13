# Dataset statistics (extension)

A read-only extension that summarizes the loaded dataset and answers small
queries about it. It is shipped `active: false` — enable it under
**Settings → Extensions**, then use the **Statistics** panel.

The summary re-reads the whole dataset, so it is **not** updated automatically:
click **Load statistics** (then **Refresh**) to compute it on demand. The query
box only runs when you ask it to.

## What it shows

- **Overview** — total images, boxes, and tagged / untagged counts.
- **By split** — images and percentage per `train` / `val` / `test`.
- **By tag** — one clickable pill per `tags.yaml` tag with its image count
  (a ⚠ marks a tag used on images but missing from `tags.yaml`).
- **By class** — boxes and images per class (from `data.yaml` `names`).
- **Labels** — images with/without labels, total boxes, boxes per image.

## The query box

Click a tag or class pill to fill the box, or type an expression. Terms are
combined with AND (whitespace) and OR (`or` / `|`); quotes keep names with
spaces together.

| Term | Meaning |
| ---- | ------- |
| `tag:smoke` | images carrying that tag (a number is the 1-based index in `tags.yaml`) |
| `class:person` | images with a box of that class (a number is the class id) |
| `split:train` | images in that split |
| `empty` | images with no boxes |
| `tagged` / `untagged` | images that have no / some tags |
| `all` (or empty) | every image |

Examples: `tag:smoke and split:train`, `tag:smoke or class:car`, `empty`.

The result is the matching count, its percentage of all images, a per-split
breakdown and the first 100 matching `split/name` keys.

## Notes

- It only **reads** files (labels and tag files), so it works in `--readonly`
  mode too.
- Tag files are read with the same convention as the Tags extension (the
  `images` segment becomes `tags`), honouring its per-dataset folder override
  when one is set, so both features agree.
- The same data is available without the panel at
  `GET /api/extension/stats` and
  `GET /api/extension/stats/query?expr=tag:smoke` (enable the package first).

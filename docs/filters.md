# Filters

A **filter** narrows the loaded image list to the images a script returns.
**Filters are chainable**: open **Settings** (⚙) and use the **Filters** tab,
which stacks up to 8 selects. Pick a filter in each select and they run **top to
bottom** — each one receives the previous one's result, applies its own logic,
and passes its result on. The last filter's output is exactly what the app shows
(count, Prev/Next, the counter jump and resume all follow it). `No filter`
clears the whole chain.

Each filter is one **Python script** in a `filters/` folder, run as:

```bash
python <filter-script> <data.yaml> <split> <input_pipe> <output_pipe>
```

with the working directory set to your user folder. Shipped filters live in
`app/filters/`; your filters live in `<home>/filters/`, are read after the
shipped ones and win on a name clash.

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
remembered per dataset and restored when you reopen the app — even after a
server restart.

`app/filters/example.py` is a comments-only template documenting the contract.

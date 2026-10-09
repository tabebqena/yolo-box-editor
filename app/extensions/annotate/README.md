# Annotate (example extension)

A reference extension that runs a small Ultralytics YOLO model over a dataset
and writes the results to a **separate** labels folder, then overlays those
boxes on the canvas so you can compare them with your own labels.

It is shipped `active: false` (nothing loads until you enable it) and is meant
to be read as a worked example — it uses the whole extension system:

| Part | File |
| ---- | ---- |
| Manifest, settings form, per-extension Python env | `extension.yaml` |
| Declared permissions | `permissions.yaml` |
| Shipped action (uses `{EXT_PYTHON}` / `{EXT_DIR}`) | `actions/annotate.yaml` |
| The model run | `scripts/annotate_all.py` |
| Backend capabilities + HTTP routes | `backend.py` |
| Sandboxed panel + canvas overlays | `panel.js` |

## Use it

1. Enable **Annotate (example)** in Settings → Extensions.
2. Build its environment (Settings button, or `ybe extension-env annotate`).
   This installs `ultralytics` into a dedicated venv under
   `<home>/extension_envs/annotate/`.
3. In the Annotate panel, set the **Model** (`.pt`), an **Output** folder and a
   **Confidence**, then click **Annotate all images**.
4. The model writes `<output>/<split>/<stem>.txt`. The panel overlays those
   boxes in a different colour. Toggle **Show extension boxes** to hide them.

Nothing here is ever written into the dataset's own `labels/`; the overlay boxes
are render-only and are not saved. To turn them into real labels, copy the files
over yourself or push them with `YBE.callbacks.setBoxes`/`addBox`.

See `docs/building-extensions.md` for a step-by-step tour.

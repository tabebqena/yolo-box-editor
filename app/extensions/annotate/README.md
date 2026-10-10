# Annotate (example extension)

A reference extension that runs a small Ultralytics YOLO model over a dataset
and writes the results to a **separate** labels folder, then overlays those
boxes on the canvas so you can compare them with your own labels.

It is shipped `active: false` (nothing loads until you enable it) and is meant
to be read as a worked example — it uses the whole extension system:

| Part | File |
| ---- | ---- |
| Manifest, per-extension Python env, panel | `extension.yaml` |
| Declared permissions | `permissions.yaml` |
| The model run | `scripts/annotate_all.py` |
| Backend capabilities + HTTP routes + async run | `backend.py` |
| Sandboxed panel + canvas overlays | `panel.js` |

## Use it

1. Enable **Annotate (example)** in Settings → Extensions.
2. Build its environment (Settings button, or `ybe extension-env annotate`).
   This installs `ultralytics` into a dedicated venv under
   `<home>/extension_envs/annotate/`.
3. In the Annotate panel, set the **Model** (`.pt`), an **Output** folder, a
   **Confidence** and, optionally, the **Model classes** (comma-separated names
   in the model's own order), then click **Annotate all images**. The panel is
   the single place these options live; it remembers them for next time.
4. The model writes `<output>/<split>/<stem>.txt`. The panel overlays those
   boxes in a different colour. Toggle **Show extension boxes** to hide them.

The model's class names are used to label the overlays. Leave **Model classes**
empty to fall back to the dataset's own class names; after a run the field is
filled automatically from the names the model reports, and an explicit value
overrides that.

The run happens in the background: the panel starts it and then polls the
backend, showing **done / total** (and a progress bar) until it finishes. The
button is disabled while a run is in progress, and the overlays keep refreshing
as labels are written, so you can browse the dataset while it runs. Run output
is written to `<home>/.annotate_run.log`.

Nothing here is ever written into the dataset's own `labels/`; the overlay boxes
are render-only and are not saved. To turn them into real labels, copy the files
over yourself or push them with `YBE.callbacks.setBoxes`/`addBox`.

See `docs/building-extensions.md` for a step-by-step tour.

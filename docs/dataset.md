# Dataset, files and formats

## Files and folders

The app is split into a relocatable **code folder** and your **user folder**:

```
<root>/
├── .venv/                    virtual environment (created by the installer)
├── actions/ hooks/ filters/ scripts/ shortcuts.txt   your files
├── config.json               your app state (recent datasets, views, settings)
└── app/                      the shipped app (replaced on upgrade)
    ├── app.py static/ templates/ requirements.txt VERSION
    └── actions/ hooks/ filters/ scripts/ shortcuts.txt   built-ins
```

The user folder is `--home <dir>`, else the `YBX_HOME` environment variable,
else **the parent of `app.py`**. Because the code lives in `app/`, that parent
is the repo root in a clone and the install root in an installed copy — so both
behave the same with no flags. Your files are read after the shipped ones and
win on a name clash. The app creates the folders when they are missing and logs
`[ybe] user dir: …` (override with `--home`).

### State is cross-browser

A single `config.json` in the user folder holds all per-user state:

- `recent` — the recently opened `data.yaml` paths;
- `views` — per-dataset split, filter chain, tags folder and disabled
  extensions;
- `settings` — General/Layout preferences, panel sizes, floating-window
  positions and the last image reached.

Your UI settings are also written to the browser; a browser you have not used
before starts from the saved `config.json` values, while a value you change in a
given browser is remembered there and wins over the saved one. The last image is
remembered **per dataset and per split**, so any browser resumes where you left
off, and restarting the server reopens the dataset in the same view. The old
`.recent_data_yamls.json`, `.view_state.json` and `.settings.json` files are
merged into `config.json` automatically on first start and then removed.

## data.yaml format

```yaml
path: /path/to/dataset_root      # optional; defaults to the data.yaml directory
train: images/train              # relative to `path`
val: images/val
test: images/test                # optional

nc: 3
names: ['cat', 'dog', 'bird']    # one-line list, or a block form
```

- `path` defaults to the folder containing `data.yaml`.
- `train`, `val`, `test` are image folders. For each one the labels folder is
  the same path with an `images` segment replaced by `labels`
  (`images/train` → `labels/train`), or a sibling `labels/<name>` when no
  `images` segment exists.
- Class names come from `names:`. If absent, class names are derived from the
  highest class id found in existing label files.

## Label format

Each image `foo.jpg` has a label file `foo.txt` in the corresponding labels
folder. Each line:

```
<class_id> <x_center> <y_center> <width> <height>
```

Coordinates are normalized to `0..1` relative to the image dimensions.

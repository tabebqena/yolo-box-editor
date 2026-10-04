"""Filter-chain runtime: run a chain of filters and cache its result.

A chain narrows the scanned image list; each filter reads candidate absolute
paths from its input pipe and writes the kept ones to its output pipe, which
feeds the next filter. Results are cached in `state.STATE` for the UI.
"""

import os
import shutil
import subprocess
import sys
import tempfile

from ybe import config, state
from ybe.dataset import _split_by_name, read_classes
from ybe.extensions import (
    effective_filter_arguments,
    load_filters,
    resolve_filter_options,
)
from ybe.pipes import _subprocess_env, build_command
from ybe.tags import read_tags_yaml


def _entry_path(entry):
    """Absolute path of a scanned `{split, name}` entry (or None)."""
    split = _split_by_name(entry["split"])
    if split is None:
        return None
    return os.path.abspath(os.path.join(split["images_dir"], entry["name"]))


def _known_image_paths():
    """Map every scanned image's absolute path to its `{split, name}` entry."""
    known = {}
    for entry in state.STATE["images"]:
        path = _entry_path(entry)
        if path:
            known[path] = entry
    return known


def _write_filter_input(path, entries):
    """Write one absolute image path per line (a filter's input pipe)."""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            abs_path = _entry_path(entry)
            if abs_path:
                f.write(abs_path + "\n")


def _parse_filter_output(text, known):
    """Map absolute image paths to entries, keeping only known images.

    Order is preserved and duplicates dropped. Returns (entries, skipped),
    where `skipped` counts non-blank lines that map to no scanned image.
    """
    entries, seen, skipped = [], set(), 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        entry = known.get(os.path.abspath(line))
        if entry is None:
            skipped += 1
            continue
        pair = (entry["split"], entry["name"])
        if pair in seen:
            continue
        seen.add(pair)
        entries.append(entry)
    return entries, skipped


def _read_filter_output(path, known):
    """Read a filter's output pipe; missing/unreadable means an empty result."""
    try:
        with open(path, encoding="utf-8") as f:
            return _parse_filter_output(f.read(), known)
    except OSError:
        return [], 0


def _filter_placeholder_values(flt, data_yaml, split, input_pipe, output_pipe, arguments):
    """Substitution values for a filter's steps (shared paths + pipes + args)."""
    split_entry = _split_by_name(split) if split else None
    values = {
        "DATASET_PATH": state.STATE["dataset_path"] or "",
        "DATA_YAML_PATH": data_yaml or "",
        "APP_DIR": config.BASE_DIR,
        "HOME_DIR": config.YBX_HOME,
        "APP_SCRIPT_DIR": config.APP_SCRIPT_DIR,
        "USER_SCRIPT_DIR": config.USER_SCRIPT_DIR,
        "PYTHON": sys.executable,
        "SPLIT": split or "",
        "INPUT_PIPE": input_pipe,
        "OUTPUT_PIPE": output_pipe,
        # The active split's tags folder (empty on All splits, so a helper falls
        # back to deriving it from the image path).
        "TAGS_DIR": (split_entry or {}).get("tags_dir") or "",
    }
    effective = effective_filter_arguments(flt, arguments)
    for arg in flt["arguments"]:
        key = arg["name"].upper()
        if key not in values:
            values[key] = effective.get(arg["name"], "")
    return values


def run_filter(name, data_yaml, split, input_pipe, output_pipe, arguments=None,
               filters=None):
    """Run filter `name` once; return {ok, error}.

    Every `steps` entry is a shell command; the app substitutes the shared
    placeholders, the pipe paths and each argument (as `{<NAME>}`) before it
    runs. The filter reads candidate image paths from `input_pipe` and writes the
    kept ones to `output_pipe`; the caller validates the output.
    """
    if filters is None:
        filters = load_filters()[0]
    flt = filters.get(name)
    if flt is None:
        return {"ok": False, "error": f"unknown filter: {name}"}

    values = _filter_placeholder_values(flt, data_yaml, split, input_pipe, output_pipe, arguments)
    for step in flt["steps"]:
        command = build_command(step, values)
        print(f"[ybe] filter: cwd={config.YBX_HOME} cmd={command}", file=sys.stderr)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=config.FILTER_TIMEOUT,
                cwd=config.YBX_HOME,
                env=_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "filter timed out"}
        except OSError as exc:
            return {"ok": False, "error": f"could not run filter: {exc}"}
        if proc.returncode != 0:
            detail = proc.stderr.strip() or f"exit code {proc.returncode}"
            return {"ok": False, "error": detail}
    return {"ok": True}


def _normalize_filter_chain(items):
    """Validate an active filter chain; return (chain, error).

    `items` may be strings (legacy) or `{name, arguments}` dicts. The returned
    chain fills each argument with its value/default and checks `required`.
    """
    filters, _ = load_filters()
    chain = []
    for item in items or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            return None, "invalid filter entry"
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        flt = filters.get(name)
        if flt is None:
            return None, f"unknown filter: {name}"
        effective = effective_filter_arguments(flt, item.get("arguments"))
        for arg in flt["arguments"]:
            value = effective.get(arg["name"], "")
            if arg["required"] and not value.strip():
                return None, f'Filter "{name}": argument "{arg["name"]}" is required'
            options = resolve_filter_options(arg.get("options"), read_classes(), read_tags_yaml())
            if options and value and value not in options:
                return None, (
                    f'Filter "{name}": argument "{arg["name"]}" must be one of: '
                    f'{", ".join(options)}')
        chain.append({"name": name, "arguments": effective})
    return chain, None


def run_filter_chain(chain, split):
    """Run `chain` in order, piping each result into the next.

    Each item is `{name, arguments}`. `split` selects the first filter's input
    (its images, or every scanned image when it is empty/"All"). Returns
    {ok, images, skipped, error, chain_dir}; `chain_dir` is the scratch directory
    (kept only with --keep-filter-pipes).
    """
    known = _known_image_paths()
    if not chain:
        return {"ok": True, "images": [], "skipped": 0, "error": None,
                "chain_dir": None}

    # Each run gets a private scratch directory holding the input/output pipes.
    try:
        os.makedirs(config.FILTER_PIPES_DIR, exist_ok=True)
        chain_dir = tempfile.mkdtemp(prefix="chain_", dir=config.FILTER_PIPES_DIR)
    except OSError as exc:
        return {"ok": False, "error": f"could not create filter pipes: {exc}",
                "chain_dir": None}

    filters, _ = load_filters()
    # The first filter sees the active split's images (every image on "All").
    initial = [e for e in state.STATE["images"] if e["split"] == split] if split \
        else state.STATE["images"]
    in_path = os.path.join(chain_dir, "input_0.txt")
    _write_filter_input(in_path, initial)

    entries, skipped, error = initial, 0, None
    for i, item in enumerate(chain):
        out_path = os.path.join(chain_dir, f"output_{i}.txt")
        result = run_filter(item["name"], state.STATE["data_yaml"], split, in_path,
                            out_path, item.get("arguments"), filters)
        if not result["ok"]:
            error = f'Filter "{item["name"]}" failed: {result["error"]}'
            entries = None
            break
        # Map the paths the filter kept back to scanned entries, then feed that
        # output into the next filter as its input.
        entries, skipped = _read_filter_output(out_path, known)
        in_path = out_path

    if not state.STATE["keep_filter_pipes"]:
        # Scratch dirs are disposable unless --keep-filter-pipes was given.
        shutil.rmtree(chain_dir, ignore_errors=True)
        chain_dir = None

    if error:
        return {"ok": False, "error": error, "chain_dir": chain_dir}
    return {"ok": True, "images": entries, "skipped": skipped, "error": None,
            "chain_dir": chain_dir}


def _clear_filter():
    state.STATE["active_filters"] = []
    state.STATE["filter_images"] = None
    state.STATE["filter_error"] = None


def apply_filters(items):
    """Run the filter chain for the current split and cache it in state.STATE.

    `items` is a list of `{name, arguments}` (strings are accepted as legacy;
    [] clears). Returns an error message on failure (state untouched), or None on
    success.
    """
    chain, error = _normalize_filter_chain(items)
    if error:
        return error
    if not chain:
        _clear_filter()
        return None
    result = run_filter_chain(chain, state.STATE["active_split"])
    if not result["ok"]:
        return result["error"]
    state.STATE["active_filters"] = chain
    state.STATE["filter_images"] = result["images"]
    if state.STATE["keep_filter_pipes"] and result["chain_dir"]:
        print(f"[ybe] kept filter pipes: {result['chain_dir']}", file=sys.stderr)
    state.STATE["filter_error"] = (
        f"{result['skipped']} filter line(s) ignored" if result["skipped"] else None
    )
    return None

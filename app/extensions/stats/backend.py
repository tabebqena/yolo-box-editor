"""Dataset statistics extension backend.

Computes summary statistics over the loaded dataset and answers simple queries:

* ``stats.summary`` - total images, per-split counts and percentages, boxes and
  images per class, label coverage and tag usage;
* ``stats.query`` - count (and percentage) of the images matching a small query
  language such as ``tag:smoke``, ``class:person``, ``split:train tag:2``,
  ``empty`` or ``tagged``.

It only reads `state.STATE` and the dataset's files, so it works in read-only
mode too. The same results are served by
``GET /api/extension/stats`` and ``GET /api/extension/stats/query?expr=...``.

Tag files are read with the same convention as the Tags package
(``images`` segment -> ``tags``), honouring that package's per-dataset folder
override (``<home>/.tags_extension.json``) when it exists so both features agree.
"""

import json
import os
import re

from ybe import state
from ybe.dataset import _parse_label_file, label_path, read_classes, _split_by_name
from ybe.parsing import _read_text

# The per-dataset tag-folder override the Tags package stores in the user home.
OVERRIDE_FILE = ".tags_extension.json"


# --- reading the dataset --------------------------------------------------- #
def _replace_images_segment(images_dir, component):
    """Replace the last `images` path segment with `component` (e.g. tags)."""
    parts = images_dir.replace("\\", "/").rstrip("/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = component
            return "/".join(parts)
    return os.path.normpath(
        os.path.join(images_dir, "..", component, os.path.basename(images_dir)))


def _override_folder():
    """The remembered tags-folder override for this dataset, or None."""
    key = os.path.abspath(state.STATE["data_yaml"] or "")
    if not key:
        return None
    from ybe import config
    try:
        with open(os.path.join(config.YBX_HOME, OVERRIDE_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data.get(key) if isinstance(data, dict) else None


def _tags_dir(split):
    override = _override_folder()
    if override:
        return os.path.join(override, split["name"])
    return _replace_images_segment(split["images_dir"], "tags")


def _image_tags(entry):
    """The tags saved for one image ([] when it has none / no dataset)."""
    split = _split_by_name(entry["split"])
    if split is None:
        return []
    stem = os.path.splitext(entry["name"])[0]
    path = os.path.join(_tags_dir(split), stem + ".txt")
    tags = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t and t not in tags:
                    tags.append(t)
    except OSError:
        pass
    return tags


def _image_classes(entry):
    """The class ids used by one image's label file ([] when empty/missing)."""
    path = label_path(entry)
    if not path or not os.path.isfile(path):
        return []
    return [cls for cls, *_ in _parse_label_file(path)]


def available_tags():
    """The dataset's `tags.yaml` names, in file order."""
    if not state.STATE["data_yaml"]:
        return []
    path = os.path.join(
        os.path.dirname(os.path.abspath(state.STATE["data_yaml"])), "tags.yaml")
    tags = []
    for raw in _read_text(path).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line.startswith("-"):
            continue
        name = line[1:].strip().strip("'\"")
        if name and name not in tags:
            tags.append(name)
    return tags


def _build_index():
    """Read the whole dataset once into `{available, split_names, class_names, rows}`."""
    available = available_tags()
    splits = [s["name"] for s in state.STATE["splits"]]
    class_names = list(read_classes())

    rows = []
    for entry in state.STATE["images"]:
        rows.append({
            "split": entry["split"],
            "name": entry["name"],
            "key": entry["split"] + "/" + entry["name"],
            "tags": _image_tags(entry),
            "boxes": _image_classes(entry),
        })

    # Extend the class-name list to cover any id a label file actually uses.
    max_id = max((c for row in rows for c in row["boxes"]), default=-1)
    while len(class_names) <= max_id:
        class_names.append("class_%d" % len(class_names))

    return {
        "available": available,
        "split_names": splits,
        "class_names": class_names,
        "rows": rows,
    }


# --- summary --------------------------------------------------------------- #
def _pct(n, total):
    return round(n * 100.0 / total, 1) if total else 0.0


def _cap_summary():
    """The full overview as plain JSON data."""
    index = _build_index()
    rows = index["rows"]
    total = len(rows)

    split_counts = {name: 0 for name in index["split_names"]}
    tag_counts = {name: 0 for name in index["available"]}
    unknown_counts = {}
    class_boxes = {}
    class_images = {}
    tagged = 0
    with_labels = 0
    total_boxes = 0

    for row in rows:
        split_counts[row["split"]] = split_counts.get(row["split"], 0) + 1

        if row["tags"]:
            tagged += 1
        for tag in row["tags"]:
            if tag in tag_counts:
                tag_counts[tag] += 1
            else:
                unknown_counts[tag] = unknown_counts.get(tag, 0) + 1

        if row["boxes"]:
            with_labels += 1
            total_boxes += len(row["boxes"])
        for cls in set(row["boxes"]):
            class_images[cls] = class_images.get(cls, 0) + 1
        for cls in row["boxes"]:
            class_boxes[cls] = class_boxes.get(cls, 0) + 1

    classes = []
    for cid, name in enumerate(index["class_names"]):
        boxes = class_boxes.get(cid, 0)
        images = class_images.get(cid, 0)
        classes.append({
            "id": cid,
            "name": name,
            "boxes": boxes,
            "images": images,
            "percent_images": _pct(images, total),
        })

    tags = [
        {"name": name, "images": count, "percent": _pct(count, total)}
        for name, count in tag_counts.items()
    ]
    unknown = sorted(
        ({"name": name, "images": count, "percent": _pct(count, total)}
         for name, count in unknown_counts.items()),
        key=lambda t: (-t["images"], t["name"]))

    return {
        "loaded": bool(state.STATE["data_yaml"]),
        "data_yaml": state.STATE["data_yaml"],
        "dataset_path": state.STATE["dataset_path"],
        "total": total,
        "splits": [
            {"name": name, "images": split_counts.get(name, 0),
             "percent": _pct(split_counts.get(name, 0), total)}
            for name in index["split_names"]
        ],
        "tags": {
            "available": tags,
            "tagged": tagged,
            "untagged": total - tagged,
            "unknown": unknown,
        },
        "classes": classes,
        "labels": {
            "with_labels": with_labels,
            "empty": total - with_labels,
            "boxes": total_boxes,
            "boxes_per_image": round(total_boxes / total, 2) if total else 0.0,
        },
    }


# --- query language -------------------------------------------------------- #
# Terms are separated by whitespace (AND); `or` / `|` splits alternatives (OR).
#   tag:<name|N>   images carrying a tag (N = 1-based index into tags.yaml)
#   class:<name|id> images with a box of that class
#   split:<name>   images in that split
#   empty / tagged / untagged / all
def _resolve_tag(value, available):
    if value.isdigit():
        i = int(value)
        if 1 <= i <= len(available):
            return available[i - 1]
    return value


def _resolve_class(value, class_names):
    if value.isdigit():
        i = int(value)
        if 0 <= i < len(class_names):
            return i
    for i, name in enumerate(class_names):
        if name.lower() == value.lower():
            return i
    raise ValueError('unknown class: "%s"' % value)


def _parse_term(token, available, class_names, split_names):
    low = token.lower()
    if low in ("*", "all", "any"):
        return ("*", None, "any")
    if low == "empty":
        return ("empty", None, "no boxes")
    if low == "tagged":
        return ("tagged", None, "has tags")
    if low == "untagged":
        return ("untagged", None, "no tags")
    if ":" in token:
        key, _, value = token.partition(":")
        key = key.lower().strip()
        value = value.strip().strip("'\"")
        if key in ("tag", "tags"):
            name = _resolve_tag(value, available)
            return ("tag", name, 'tag "%s"' % name)
        if key in ("class", "classes", "cls"):
            cid = _resolve_class(value, class_names)
            return ("class", cid, 'class "%s"' % class_names[cid])
        if key == "split":
            for name in split_names:
                if name.lower() == value.lower():
                    return ("split", name, 'split "%s"' % name)
            raise ValueError('unknown split: "%s"' % value)
    raise ValueError('unknown query term: "%s"' % token)


def _parse_query(expr, available, class_names, split_names):
    """Parse an expression into `([[(kind, value), ...], ...], description)`."""
    text = (expr or "").strip()
    if not text or text.lower() in ("*", "all", "any"):
        return [[("*", None)]], "all images"

    groups, descriptions = [], []
    for chunk in re.split(r"\s+(?:or|\|)\s+", text, flags=re.IGNORECASE):
        terms, labels = [], []
        for token in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', chunk.strip()):
            if not token or token.lower() == "and":
                continue
            kind, value, label = _parse_term(
                token, available, class_names, split_names)
            terms.append((kind, value))
            labels.append(label)
        if terms:
            groups.append(terms)
            descriptions.append(" and ".join(labels))
    if not groups:
        return [[("*", None)]], "all images"
    return groups, " or ".join(descriptions)


def _matches(row, groups):
    for group in groups:
        if all(_match_term(row, kind, value) for kind, value in group):
            return True
    return False


def _match_term(row, kind, value):
    if kind == "*":
        return True
    if kind == "empty":
        return not row["boxes"]
    if kind == "tagged":
        return bool(row["tags"])
    if kind == "untagged":
        return not row["tags"]
    if kind == "tag":
        return value in row["tags"]
    if kind == "class":
        return value in row["boxes"]
    if kind == "split":
        return row["split"] == value
    return False


def _cap_query(expr=""):
    """Count the images matching `expr`, with a percentage and a split breakdown."""
    index = _build_index()
    groups, description = _parse_query(
        expr, index["available"], index["class_names"], index["split_names"])
    matched = [row for row in index["rows"] if _matches(row, groups)]

    by_split = {}
    for row in matched:
        by_split[row["split"]] = by_split.get(row["split"], 0) + 1

    total = len(index["rows"])
    return {
        "expr": expr,
        "description": description,
        "count": len(matched),
        "total": total,
        "percent": _pct(len(matched), total),
        "by_split": by_split,
        "images": [row["key"] for row in matched[:100]],
        "truncated": len(matched) > 100,
    }


# --- HTTP routes (declared for the host's runtime dispatcher) -------------- #
def _get_summary():
    from flask import jsonify
    return jsonify({"ok": True, "summary": _cap_summary()})


def _get_query():
    from flask import jsonify, request
    expr = request.args.get("expr", "")
    try:
        result = _cap_query(expr)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "result": result})


# Mounted under `/api/extension/<prefix>` (prefix = the package id `stats`).
extension_routes = (
    {"rule": "", "methods": ["GET"], "handler": _get_summary},
    {"rule": "/query", "methods": ["GET"], "handler": _get_query},
)


def register(ctx):
    """Return the capability table the panel calls through `YBE.call`."""
    return {
        "capabilities": {
            "stats.summary": lambda: _cap_summary(),
            "stats.query": lambda expr="": _cap_query(expr),
        },
    }

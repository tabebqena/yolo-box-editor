#!/usr/bin/env python3
"""Annotate every image of a YOLO dataset with a small model (example script).

Reads `data.yaml`, runs an Ultralytics YOLO model over each image and writes
YOLO label files into a SEPARATE output folder (mirroring the splits) — never
the dataset's own `labels/`. It is launched by the package action with the
package's own interpreter (`{EXT_PYTHON}`), so `ultralytics` does not need to be
installed in the app's environment.

Usage:
    annotate_all.py --data data.yaml --out OUT_DIR --model model.pt [--conf 0.25]
                    [--progress PROGRESS_JSON] [--classes CLASSES_JSON]
"""

import argparse
import json
import os
import sys

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def parse_data_yaml(path):
    """A tiny `data.yaml` reader (no PyYAML). Returns (base, splits, names).

    `base` is the resolved dataset root, `splits` maps train/val/test to their
    (relative or absolute) image folders and `names` maps class ids to names.
    """
    root = os.path.dirname(os.path.abspath(path))
    base = root
    splits = {}
    names = {}
    in_names = False
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if in_names and line[:1] == " ":
                key, _, value = line.strip().partition(":")
                value = value.strip().strip("'\"")
                if value:
                    try:
                        names[int(key)] = value
                    except ValueError:
                        pass
                continue
            in_names = False
            if ":" not in line:
                continue
            key, _, value = line.strip().partition(":")
            key, value = key.strip(), value.strip()
            if key == "path":
                base = value
            elif key in ("train", "val", "test") and value:
                splits[key] = value
            elif key == "names":
                if value.startswith("["):
                    for i, name in enumerate(value.strip("[]").split(",")):
                        name = name.strip().strip("'\"")
                        if name:
                            names[i] = name
                else:
                    in_names = True
    if not os.path.isabs(base):
        base = os.path.join(root, base)
    return os.path.normpath(base), splits, names


def image_files(folder):
    """Sorted image paths directly inside `folder` (empty when missing)."""
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if os.path.splitext(name)[1].lower() in IMAGE_EXTS
        and os.path.isfile(os.path.join(folder, name)))


def write_labels(path, lines):
    """Write YOLO label lines to `path` (creating the folder)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        if lines:
            handle.write("\n")


def write_progress(path, done, total, current=None, phase="running", error=None):
    """Write the run's progress to `path` atomically (no-op without a path).

    The backend reads this file while the run is in flight so the panel can show
    "done / total" instead of waiting on one long request.
    """
    if not path:
        return
    payload = {"done": done, "total": total, "current": current, "phase": phase}
    if error:
        payload["error"] = error
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def write_classes(path, names):
    """Record the model's class names so the panel can label overlays with them.

    The model's `names` is normally a `{index: name}` mapping; a list is also
    accepted. Written atomically, and ignored on any error.
    """
    if not path or not names:
        return
    try:
        if isinstance(names, dict):
            data = {str(key): str(value) for key, value in names.items()}
        else:
            data = [str(value) for value in names]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        pass


def boxes_to_lines(results):
    """Convert Ultralytics results into normalized YOLO `class cx cy w h` lines."""
    lines = []
    for result in results:
        height, width = result.orig_shape
        for box in result.boxes:
            cls = int(box.cls[0])
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            cx = ((x1 + x2) / 2) / width
            cy = ((y1 + y2) / 2) / height
            bw = (x2 - x1) / width
            bh = (y2 - y1) / height
            lines.append(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="Annotate a dataset with a YOLO model.")
    parser.add_argument("--data", required=True, help="path to data.yaml")
    parser.add_argument("--out", required=True, help="output folder for the labels")
    parser.add_argument("--model", required=True, help="model weights (.pt)")
    parser.add_argument("--conf", type=float, default=0.25, help="confidence threshold")
    parser.add_argument("--progress", help="file to write progress JSON to")
    parser.add_argument("--classes", help="file to write the model's class names to")
    args = parser.parse_args(argv)

    try:
        from ultralytics import YOLO
    except ImportError:
        sys.stderr.write(
            "ultralytics is not installed in this interpreter.\n"
            "Build the extension environment first:  ybe extension-env annotate\n")
        write_progress(args.progress, 0, 0, phase="error",
                       error="ultralytics is not installed")
        return 2

    base, splits, _names = parse_data_yaml(args.data)
    out_root = os.path.abspath(os.path.expanduser(args.out))

    # Collect every image up front so the progress bar knows the total.
    jobs = []
    for split, rel in splits.items():
        images_dir = rel if os.path.isabs(rel) else os.path.join(base, rel)
        files = image_files(images_dir)
        print(f"[annotate] {split}: {len(files)} image(s)")
        jobs.extend((split, path) for path in files)
    total = len(jobs)
    write_progress(args.progress, 0, total, phase="loading")

    model = YOLO(args.model)
    write_classes(args.classes, getattr(model, "names", None))
    done = 0
    try:
        for split, image_path in jobs:
            lines = boxes_to_lines(model.predict(source=image_path, conf=args.conf,
                                                 verbose=False))
            stem = os.path.splitext(os.path.basename(image_path))[0]
            write_labels(os.path.join(out_root, split, stem + ".txt"), lines)
            done += 1
            write_progress(args.progress, done, total,
                           current=os.path.basename(image_path))
    except Exception as exc:  # noqa: BLE001 - report to the panel, then exit
        write_progress(args.progress, done, total, phase="error", error=str(exc))
        print(f"[annotate] failed: {exc}", file=sys.stderr)
        return 1
    write_progress(args.progress, done, total, phase="done")
    print(f"[annotate] wrote labels for {total} image(s) to {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for scripts/archive.py."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = ROOT / "scripts" / "archive.py"
_spec = importlib.util.spec_from_file_location("ybe_archive", _SCRIPT)
archive = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(archive)


def _dataset(tmp_path, splits=("train", "val")):
    root = tmp_path / "ds"
    root.mkdir()
    (root / "data.yaml").write_text(
        f"path: {root}\n" + "".join(f"{s}: {s}/images\n" for s in splits),
        encoding="utf-8",
    )
    return root


def _file(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_archive_path_preserves_split():
    splits = {"train", "val"}
    assert (
        archive.archive_path("/d/train/images/a.jpg", splits)
        == "/d/archive/train/images/a.jpg"
    )
    assert (
        archive.archive_path("/d/images/train/a.jpg", splits)
        == "/d/images/archive/train/a.jpg"
    )
    assert archive.archive_path("/d/other/a.jpg", splits) is None


def test_tag_path_for():
    assert archive.tag_path_for("/d/train/labels/a.txt") == "/d/train/tags/a.txt"
    assert archive.tag_path_for("") is None
    assert archive.tag_path_for("/d/train/a.txt") is None


def test_main_moves_image_label_and_tag(tmp_path):
    root = _dataset(tmp_path)
    img = _file(root / "train" / "images" / "a.jpg")
    lab = _file(root / "train" / "labels" / "a.txt")
    tag = _file(root / "train" / "tags" / "a.txt")
    assert archive.main([str(root / "data.yaml"), str(img), str(lab)]) == 0
    assert (root / "archive" / "train" / "images" / "a.jpg").is_file()
    assert (root / "archive" / "train" / "labels" / "a.txt").is_file()
    assert (root / "archive" / "train" / "tags" / "a.txt").is_file()
    assert not img.exists() and not lab.exists() and not tag.exists()


def test_main_splits_do_not_collide(tmp_path):
    root = _dataset(tmp_path)
    tr = _file(root / "train" / "images" / "a.jpg")
    _file(root / "train" / "labels" / "a.txt")
    va = _file(root / "val" / "images" / "a.jpg")
    _file(root / "val" / "labels" / "a.txt")
    data = str(root / "data.yaml")
    assert archive.main([data, str(tr), str(root / "train" / "labels" / "a.txt")]) == 0
    assert archive.main([data, str(va), str(root / "val" / "labels" / "a.txt")]) == 0
    assert (root / "archive" / "train" / "images" / "a.jpg").is_file()
    assert (root / "archive" / "val" / "images" / "a.jpg").is_file()


def test_main_skips_missing_label_and_tag(tmp_path):
    root = _dataset(tmp_path)
    img = _file(root / "train" / "images" / "a.jpg")
    data = str(root / "data.yaml")
    assert archive.main([data, str(img), str(root / "train" / "labels" / "a.txt")]) == 0
    assert (root / "archive" / "train" / "images" / "a.jpg").is_file()


def test_main_refuses_existing_destination(tmp_path):
    root = _dataset(tmp_path)
    img = _file(root / "train" / "images" / "a.jpg")
    lab = _file(root / "train" / "labels" / "a.txt")
    _file(root / "archive" / "train" / "images" / "a.jpg")  # occupied
    assert archive.main([str(root / "data.yaml"), str(img), str(lab)]) == 1
    assert img.is_file()  # nothing was moved
    assert lab.is_file()


def test_main_missing_image(tmp_path):
    root = _dataset(tmp_path)
    missing = root / "train" / "images" / "nope.jpg"
    assert archive.main([str(root / "data.yaml"), str(missing), ""]) == 1

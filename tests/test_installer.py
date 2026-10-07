"""Tests for the standalone installer `ybx.py` (offline parts only)."""

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_installer():
    spec = importlib.util.spec_from_file_location("ybx_installer", ROOT / "ybx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ybx = _load_installer()


def test_parse_version():
    assert ybx.parse_version("v2.2.0") == (2, 2, 0)
    assert ybx.parse_version("7.14") == (7, 14)
    assert ybx.parse_version("main") is None
    assert ybx.parse_version(None) is None


def test_is_newer():
    assert ybx.is_newer("7.14.0", "7.9.0")
    assert not ybx.is_newer("7.9.0", "7.14.0")
    assert not ybx.is_newer("7.14.0", "7.14.0")
    assert ybx.is_newer("2.0", "1.99.99")
    assert not ybx.is_newer("", "1.0")
    assert ybx.is_newer("1.0", "")
    assert ybx.is_newer("weird", "1.0")
    assert not ybx.is_newer("1.0", "weird")


def test_find_app_dir_repo_and_archive(tmp_path):
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "app.py").write_text("")
    (repo / "app" / "VERSION").write_text("1.0")
    assert ybx.find_app_dir(str(repo)) == str(repo / "app")

    archive = tmp_path / "yolo-box-editor-abc"
    (archive / "app").mkdir(parents=True)
    (archive / "app" / "app.py").write_text("")
    (archive / "app" / "VERSION").write_text("1.0")
    assert ybx.find_app_dir(str(tmp_path)) == str(archive / "app")

    assert ybx.find_app_dir(str(tmp_path / "nope")) is None


def test_place_app_is_atomic_and_keeps_user_files(tmp_path):
    src = tmp_path / "src"
    (src / "scripts").mkdir(parents=True)
    (src / "app.py").write_text("new")
    (src / "VERSION").write_text("9.9.9")
    (src / "scripts" / "helper.py").write_text("x")

    dest = tmp_path / "dest"
    (dest / "app").mkdir(parents=True)
    (dest / "app" / "app.py").write_text("old")
    (dest / "shortcuts.txt").write_text("mine")

    ybx.place_app(str(src), str(dest))

    assert (dest / "app" / "app.py").read_text() == "new"
    assert (dest / "app" / "VERSION").read_text() == "9.9.9"
    assert (dest / "shortcuts.txt").read_text() == "mine"
    # The staging/backup directories are cleaned up.
    assert not [p for p in dest.iterdir() if p.name.startswith(".app.")]


def test_place_app_rejects_incomplete_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("x")
    with pytest.raises(SystemExit):
        ybx.place_app(str(src), str(tmp_path / "dest"))


def test_install_self_copies_from_the_installed_tree(tmp_path):
    tree = tmp_path / "tree"
    (tree / "app").mkdir(parents=True)
    (tree / "app" / "app.py").write_text("")
    (tree / "app" / "VERSION").write_text("1.0")
    (tree / "ybx.py").write_text("NEW INSTALLER")

    opts = ybx.Options()
    opts.dir = str(tmp_path / "dest")
    os.makedirs(opts.dir)

    ybx.install_self(opts, str(tree / "app"))
    assert (Path(opts.dir) / "ybx.py").read_text() == "NEW INSTALLER"


def test_parse_args():
    opts = ybx.parse_args(["install", "--dir", "/tmp/x", "--no-start", "--from", "."])
    assert opts.cmd == "install"
    assert opts.dir == "/tmp/x"
    assert opts.start is False
    assert opts.from_path == "."

    opts = ybx.parse_args(["--home=/tmp/y", "update", "--latest"])
    assert opts.cmd == "update"
    assert opts.dir == "/tmp/y"
    assert opts.latest is True

    with pytest.raises(SystemExit):
        ybx.parse_args(["install", "--nope"])


def test_cmd_version_reports_installed_and_missing(tmp_path, capsys):
    opts = ybx.Options()
    opts.dir = str(tmp_path)
    assert ybx.cmd_version(opts) == 1
    assert "not installed" in capsys.readouterr().out

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "VERSION").write_text("7.14.0")
    assert ybx.cmd_version(opts) == 0
    assert "7.14.0" in capsys.readouterr().out


def _make_source_tree(tmp_path):
    tree = tmp_path / "tree"
    (tree / "app" / "scripts").mkdir(parents=True)
    (tree / "app" / "app.py").write_text("# app\n")
    (tree / "app" / "VERSION").write_text("7.14.0\n")
    (tree / "app" / "launcher.sh.in").write_text(
        'exec "@VENV@/bin/python" "@DIR@/app/launcher.py" --home "@DIR@" "$@"\n'
    )
    (tree / "app" / "requirements.txt").write_text("Flask\n")
    (tree / "app" / "scripts" / "helper.py").write_text("# helper\n")
    (tree / "ybx.py").write_text("SOURCE INSTALLER")
    return tree


def test_do_install_from_source_offline(tmp_path, monkeypatch):
    tree = _make_source_tree(tmp_path)
    install_dir = tmp_path / "installed"
    bin_path = tmp_path / "bin"
    monkeypatch.setattr(ybx, "setup_venv", lambda opts: None)
    monkeypatch.setattr(ybx, "maybe_start", lambda opts: None)
    monkeypatch.setattr(ybx, "bin_dir", lambda: str(bin_path))

    opts = ybx.parse_args(["install", "--from", str(tree), "--dir", str(install_dir), "--no-start"])
    ybx.do_install(opts)

    assert (install_dir / "app" / "app.py").read_text() == "# app\n"
    assert (install_dir / "app" / "VERSION").read_text() == "7.14.0\n"
    for name in ybx.USER_DIRS:
        assert (install_dir / name).is_dir()
    assert (install_dir / "ybx.py").read_text() == "SOURCE INSTALLER"

    launcher = bin_path / "yolo-box-editor"
    assert launcher.is_file()
    text = launcher.read_text()
    assert str(install_dir) in text and "@DIR@" not in text and "@VENV@" not in text
    assert (bin_path / "ybe").exists()


def test_uninstall_keeps_user_files(tmp_path, monkeypatch):
    install_dir = tmp_path / "installed"
    (install_dir / "app").mkdir(parents=True)
    (install_dir / ".venv").mkdir()
    (install_dir / "actions").mkdir()
    (install_dir / "ybx.py").write_text("x")
    (install_dir / "shortcuts.txt").write_text("mine")

    monkeypatch.setattr(ybx, "stop_installed", lambda opts: None)
    monkeypatch.setattr(ybx, "remove_launchers", lambda opts: None)

    opts = ybx.parse_args(["uninstall", "--dir", str(install_dir)])
    assert ybx.cmd_uninstall(opts) == 0

    assert not (install_dir / "app").exists()
    assert not (install_dir / ".venv").exists()
    assert not (install_dir / "ybx.py").exists()
    assert (install_dir / "actions").is_dir()
    assert (install_dir / "shortcuts.txt").read_text() == "mine"


def test_uninstall_purge_needs_yes_when_not_tty(tmp_path, monkeypatch):
    install_dir = tmp_path / "installed"
    install_dir.mkdir()
    (install_dir / "app").mkdir()
    monkeypatch.setattr(ybx, "stop_installed", lambda opts: None)
    monkeypatch.setattr(ybx, "remove_launchers", lambda opts: None)
    monkeypatch.setattr(ybx.sys.stdin, "isatty", lambda: False)

    opts = ybx.parse_args(["uninstall", "--dir", str(install_dir), "--purge"])
    with pytest.raises(SystemExit):
        ybx.cmd_uninstall(opts)


def test_render_launcher_substitutes_paths(tmp_path):
    template = tmp_path / "launcher.sh.in"
    template.write_text('exec "@VENV@/bin/python" "@DIR@/app/launcher.py" --home "@DIR@" "$@"\n')
    opts = ybx.Options()
    opts.dir = str(tmp_path / "home")
    text = ybx.render_launcher(str(template), opts)
    assert str(tmp_path / "home") in text
    assert "@DIR@" not in text and "@VENV@" not in text
    assert os.path.join(opts.dir, ".venv") in text

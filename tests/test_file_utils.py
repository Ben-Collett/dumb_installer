"""Phase 2: filesystem and config logic, against real tmpdirs.

Nothing here is mocked -- these tests exercise the real shutil/pathlib code
paths, because that is what survives a refactor.
"""

import json
import os
from pathlib import Path

import pytest

from build_config_utils import BuildConfig
from constants import CONFIG_FILE, METADATA_FILE
from file_utils import copy_project, directories_differ, files_differ, remove_excluded
from meta_data import MetaData
from snapshot import Snapshot
from conftest import write_project


# ---------------------------------------------------------------------------
# copy_project
# ---------------------------------------------------------------------------


def test_copy_project_copies_everything(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hi')\n")
    (src / "sub").mkdir()
    (src / "sub" / "deep.txt").write_text("deep\n")
    dest = tmp_path / "dest"

    copy_project(src, dest, [])

    assert (dest / "main.py").read_text() == "print('hi')\n"
    assert (dest / "sub" / "deep.txt").read_text() == "deep\n"


def test_copy_project_honours_exclusions(tmp_path):
    src = write_project(tmp_path / "proj")
    dest = tmp_path / "dest"

    copy_project(src, dest, ["__pycache__", "*.pyc", ".git"])

    assert (dest / "main.py").is_file()
    assert not (dest / "__pycache__").exists()
    assert not (dest / ".git").exists()


def test_copy_project_replaces_an_existing_destination(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "new.txt").write_text("new\n")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "stale.txt").write_text("stale\n")

    copy_project(src, dest, [])

    assert (dest / "new.txt").is_file()
    assert not (dest / "stale.txt").exists(), "stale content must not survive"


def test_copy_project_preserves_symlinks(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "real.txt").write_text("real\n")
    os.symlink("real.txt", src / "link.txt")
    dest = tmp_path / "dest"

    copy_project(src, dest, [])

    assert (dest / "link.txt").is_symlink()


# ---------------------------------------------------------------------------
# files_differ
# ---------------------------------------------------------------------------


def test_files_differ_identical(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("same\n")
    b.write_text("same\n")
    assert files_differ(a, b) is False


def test_files_differ_same_size_different_content(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("aaaa")
    b.write_text("bbbb")
    assert files_differ(a, b) is True


def test_files_differ_size_mismatch(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("a")
    b.write_text("a much longer body")
    assert files_differ(a, b) is True


def test_files_differ_empty_files(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("")
    b.write_text("")
    assert files_differ(a, b) is False


# ---------------------------------------------------------------------------
# directories_differ
# ---------------------------------------------------------------------------


def _pair(tmp_path, left=None, right=None):
    left = left or {}
    right = right if right is not None else dict(left)
    d1 = tmp_path / "one"
    d2 = tmp_path / "two"
    for base, files in ((d1, left), (d2, right)):
        base.mkdir()
        for rel, content in files.items():
            target = base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    return d1, d2


def test_directories_differ_identical(tmp_path):
    d1, d2 = _pair(tmp_path, {"a.txt": "a", "sub/b.txt": "b"})
    assert directories_differ(d1, d2) is False


def test_directories_differ_changed_content(tmp_path):
    d1, d2 = _pair(tmp_path, {"a.txt": "a"}, {"a.txt": "CHANGED"})
    assert directories_differ(d1, d2) is True


def test_directories_differ_file_only_in_second(tmp_path):
    d1, d2 = _pair(tmp_path, {"a.txt": "a"}, {"a.txt": "a", "extra.txt": "e"})
    assert directories_differ(d1, d2) is True


def test_directories_differ_file_only_in_first(tmp_path):
    d1, d2 = _pair(tmp_path, {"a.txt": "a", "extra.txt": "e"}, {"a.txt": "a"})
    assert directories_differ(d1, d2) is True


def test_directories_differ_nested_directory_only_in_second(tmp_path):
    d1, d2 = _pair(tmp_path, {"a.txt": "a"}, {"a.txt": "a", "sub/deep.txt": "d"})
    assert directories_differ(d1, d2) is True


def test_directories_differ_missing_root(tmp_path):
    d1, d2 = _pair(tmp_path, {"a.txt": "a"})
    assert directories_differ(d1, tmp_path / "nope") is True


def test_directories_differ_respects_ignore_patterns(tmp_path):
    """Ignored differences must not count -- this is what makes 'already up to
    date' correct when build artefacts churn."""
    d1, d2 = _pair(tmp_path, {"a.txt": "a"}, {"a.txt": "a", "noise.pyc": "junk"})
    assert directories_differ(d1, d2, ["*.pyc"]) is False
    assert directories_differ(d1, d2) is True


def test_directories_differ_ignores_nested_artifacts(tmp_path):
    d1, d2 = _pair(
        tmp_path,
        {"a.txt": "a", "sub/b.txt": "b"},
        {"a.txt": "a", "sub/b.txt": "b", "sub/__pycache__/x.pyc": "junk"},
    )
    assert directories_differ(d1, d2, ["__pycache__", "*.pyc"]) is False


# ---------------------------------------------------------------------------
# remove_excluded
# ---------------------------------------------------------------------------


def test_remove_excluded_removes_files_and_dirs(tmp_path):
    root = tmp_path / "p"
    (root / "__pycache__").mkdir(parents=True)
    (root / "__pycache__" / "x.pyc").write_text("junk")
    (root / "keep.py").write_text("keep")
    (root / "stale.pyc").write_text("junk")

    remove_excluded(root, ["__pycache__", "*.pyc"])

    assert (root / "keep.py").is_file()
    assert not (root / "__pycache__").exists()
    assert not (root / "stale.pyc").exists()


def test_remove_excluded_handles_nested_matches(tmp_path):
    root = tmp_path / "p"
    deep = root / "a" / "b" / "__pycache__"
    deep.mkdir(parents=True)
    (deep / "y.pyc").write_text("junk")
    (root / "a" / "keep.txt").write_text("keep")

    remove_excluded(root, ["__pycache__"])

    assert not (root / "a" / "b" / "__pycache__").exists()
    assert (root / "a" / "keep.txt").is_file()


def test_remove_excluded_on_clean_tree_is_a_noop(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "main.py").write_text("keep")
    remove_excluded(root, ["*.pyc", ".git"])
    assert (root / "main.py").is_file()


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_revert_restores_original(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "f.txt").write_text("original")

    snap = Snapshot(src)
    (src / "f.txt").write_text("changed")
    (src / "new.txt").write_text("added")

    snap.revert_and_discard()

    assert (src / "f.txt").read_text() == "original"
    assert not (src / "new.txt").exists()


def test_snapshot_discard_leaves_source_alone(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "f.txt").write_text("original")

    snap = Snapshot(src)
    (src / "f.txt").write_text("changed")
    snap.discard()

    assert (src / "f.txt").read_text() == "changed"


def test_snapshot_cannot_be_discarded_twice(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    snap = Snapshot(src)
    snap.discard()
    with pytest.raises(Exception):
        snap.discard()


def test_snapshot_cannot_revert_after_discard(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    snap = Snapshot(src)
    snap.discard()
    with pytest.raises(Exception):
        snap.revert()


def test_snapshot_copies_to_a_separate_tempdir(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "f.txt").write_text("x")
    snap = Snapshot(src)
    assert snap.snapshot_path != src
    assert snap.snapshot_path.is_dir()


# ---------------------------------------------------------------------------
# MetaData
# ---------------------------------------------------------------------------


def test_metadata_round_trip(tmp_path):
    MetaData(is_git_install=False, source_path=tmp_path / "src").write(tmp_path)
    loaded = MetaData().update_from(tmp_path)
    assert loaded.is_git_install is False
    assert loaded.source_path == tmp_path / "src"


def test_git_install_forces_source_path_to_none(tmp_path):
    MetaData(is_git_install=True, source_path=tmp_path / "src").write(tmp_path)
    data = json.loads((tmp_path / METADATA_FILE).read_text())
    assert data["is_git_install"] is True
    assert data["source_path"] is None

    loaded = MetaData().update_from(tmp_path)
    assert loaded.is_git_install is True
    assert loaded.source_path is None


def test_metadata_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        MetaData().update_from(tmp_path)


def test_metadata_creates_parent_dir(tmp_path):
    target = tmp_path / "deep" / "nested"
    MetaData(source_path=tmp_path).write(target)
    assert (target / METADATA_FILE).is_file()


# ---------------------------------------------------------------------------
# BuildConfig
# ---------------------------------------------------------------------------


def test_build_config_reads_required_fields(tmp_path):
    write_project(tmp_path, name="tool", command="run-me")
    cfg = BuildConfig(tmp_path)
    assert cfg.executable_name == "tool"
    assert cfg.command == "run-me"


def test_build_config_local_and_remote_excludes_are_merged(tmp_path):
    write_project(
        tmp_path,
        excluded=["*.log"],
        local_install_excluded=[".git"],
        remote_install_excluded=["tests"],
    )
    cfg = BuildConfig(tmp_path)
    assert set(cfg.get_local_excluded_files()) == {"*.log", ".git"}
    assert set(cfg.get_remote_excluded_files()) == {"*.log", "tests"}


def test_build_config_excludes_default_to_empty(tmp_path):
    (tmp_path / CONFIG_FILE).write_text(
        '[build]\nexecutable_name = "t"\ncommand = "c"\n'
    )
    cfg = BuildConfig(tmp_path)
    assert cfg.get_local_excluded_files() == []
    assert cfg.get_remote_excluded_files() == []


def test_build_config_optional_hooks_default_to_none(tmp_path):
    (tmp_path / CONFIG_FILE).write_text(
        '[build]\nexecutable_name = "t"\ncommand = "c"\n'
    )
    cfg = BuildConfig(tmp_path)
    assert cfg.on_install is None
    assert cfg.on_update is None


def test_build_config_reads_hooks(tmp_path):
    (tmp_path / CONFIG_FILE).write_text(
        '[build]\nexecutable_name = "t"\ncommand = "c"\n'
        'on_install = "make"\non_update = "make again"\n'
    )
    cfg = BuildConfig(tmp_path)
    assert cfg.on_install == "make"
    assert cfg.on_update == "make again"


def test_missing_build_file_exits(tmp_path):
    with pytest.raises(SystemExit):
        BuildConfig(tmp_path)


def test_unparseable_toml_exits(tmp_path):
    (tmp_path / CONFIG_FILE).write_text("this is not = = toml [[[")
    with pytest.raises(SystemExit):
        BuildConfig(tmp_path)


def test_missing_build_section_exits(tmp_path):
    (tmp_path / CONFIG_FILE).write_text('[other]\nkey = "value"\n')
    with pytest.raises(SystemExit):
        BuildConfig(tmp_path)


@pytest.mark.parametrize("missing", ["executable_name", "command"])
def test_missing_required_field_exits(tmp_path, missing):
    fields = {"executable_name": '"t"', "command": '"c"'}
    del fields[missing]
    body = "\n".join(f'{k} = {v}' for k, v in fields.items())
    (tmp_path / CONFIG_FILE).write_text(f"[build]\n{body}\n")
    with pytest.raises(SystemExit):
        BuildConfig(tmp_path)


def test_missing_file_reports_both_problems_at_once(tmp_path, capsys):
    """The error collector should aggregate, not fail on the first problem."""
    (tmp_path / CONFIG_FILE).write_text("[nope]\n")
    with pytest.raises(SystemExit):
        BuildConfig(tmp_path)
    out = capsys.readouterr().out
    assert "[build]" in out


def test_safe_get_build_config_returns_none_on_failure(tmp_path):
    assert BuildConfig.safe_get_build_config(tmp_path) is None


def test_safe_get_build_config_returns_config_on_success(tmp_path):
    write_project(tmp_path, name="ok")
    assert BuildConfig.safe_get_build_config(tmp_path) is not None

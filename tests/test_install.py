"""Phase 4/5: end-to-end CLI behaviour inside the bwrap sandbox.

These assert on exit codes, filesystem state and generated wrapper contents --
never on message wording (see TESTING_PLAN.md section 3.3).
"""

import json
import os
import stat
from pathlib import Path

import pytest

from conftest import USAGE_EXIT, requires_bwrap, write_project

pytestmark = [requires_bwrap, pytest.mark.sandbox]

WRAPPER_MODE = (
    stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    | stat.S_IRGRP | stat.S_IXGRP
    | stat.S_IROTH | stat.S_IXOTH
)


def wrapper_text(sandbox, name):
    return sandbox.wrapper_path(name).read_text()


# ===========================================================================
# Local install
# ===========================================================================


def test_install_copies_project_and_writes_wrapper(sandbox, project):
    result = sandbox.run([], cwd=project)
    assert result.returncode == 0, result.stdout + result.stderr

    installed = sandbox.project_path("mytool")
    assert (installed / "main.py").is_file()
    assert (installed / "dumb_build.toml").is_file()
    assert sandbox.wrapper_path("mytool").is_file()


def test_install_applies_exclusions(sandbox, project):
    result = sandbox.run([], cwd=project)
    assert result.returncode == 0
    installed = sandbox.project_path("mytool")
    assert not (installed / "__pycache__").exists()
    assert not (installed / ".git").exists()


def test_wrapper_contains_project_dir_and_command(sandbox, project):
    result = sandbox.run([], cwd=project)
    assert result.returncode == 0
    text = wrapper_text(sandbox, "mytool")
    assert text.startswith("#!/usr/bin/env sh\n")
    assert "dumb_project_dir=/usr/lib/dumb_builds/mytool" in text
    assert 'python $dumb_project_dir/main.py "$@"' in text


def test_wrapper_is_executable(sandbox, project):
    result = sandbox.run([], cwd=project)
    assert result.returncode == 0
    assert sandbox.wrapper_path("mytool").stat().st_mode & 0o777 == WRAPPER_MODE


def test_installed_wrapper_actually_runs(sandbox, project):
    """The end-to-end promise: the generated wrapper executes the project."""
    project.joinpath("main.py").write_text(
        "import sys\nprint('ran', *sys.argv[1:])\n"
    )
    assert sandbox.run([], cwd=project).returncode == 0

    import subprocess
    from conftest import REPO_ROOT

    # The wrapper is on PATH inside the sandbox, so invoke it by name.
    run = subprocess.run(
        sandbox.argv(["mytool", "one", "two"], env={"SUDO_UID": "1000"}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert "ran one two" in run.stdout


def test_wrapper_forwards_arguments(sandbox, project):
    project.joinpath("main.py").write_text("import sys\nprint(len(sys.argv)-1)\n")
    assert sandbox.run([], cwd=project).returncode == 0

    import subprocess

    run = subprocess.run(
        sandbox.argv(["mytool", "a", "b", "c"], env={"SUDO_UID": "1000"}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "3"


def test_install_writes_metadata(sandbox, project):
    assert sandbox.run([], cwd=project).returncode == 0
    meta_file = sandbox.project_path("mytool") / ".dumb_install_metadata.json"
    assert meta_file.is_file()
    data = json.loads(meta_file.read_text())
    assert data["is_git_install"] is False
    assert data["source_path"]


def test_name_override_changes_wrapper_only(sandbox, project):
    result = sandbox.run(["-n", "custom"], cwd=project)
    assert result.returncode == 0
    assert sandbox.wrapper_path("custom").is_file()
    assert sandbox.project_path("custom").is_dir()
    assert "dumb_project_dir=/usr/lib/dumb_builds/custom" in wrapper_text(sandbox, "custom")


def test_reinstall_replaces_previous_content(sandbox, project):
    assert sandbox.run([], cwd=project).returncode == 0
    stale = sandbox.project_path("mytool") / "stale.txt"
    stale.write_text("old\n")

    assert sandbox.run([], cwd=project).returncode == 0
    assert not stale.exists(), "a reinstall must not leave stale files behind"


def test_install_without_build_file_fails(sandbox, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = sandbox.run([], cwd=empty)
    assert result.returncode != 0
    assert not sandbox.wrapper_path("mytool").exists()


def test_install_with_unparseable_build_file_fails(sandbox, tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "dumb_build.toml").write_text("nonsense = = = [[[")
    result = sandbox.run([], cwd=bad)
    assert result.returncode != 0
    assert not list(sandbox.bin_dir.iterdir())


def test_install_missing_command_fails(sandbox, tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "dumb_build.toml").write_text('[build]\nexecutable_name = "t"\n')
    result = sandbox.run([], cwd=bad)
    assert result.returncode != 0
    assert not list(sandbox.bin_dir.iterdir())


# ===========================================================================
# Per-user (non-sudo) install
# ===========================================================================


def test_user_install_uses_configured_user_paths(sandbox, project):
    sandbox.write_user_config()
    result = sandbox.run([], cwd=project, as_root=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (sandbox.user_lib / "mytool" / "main.py").is_file()
    assert (sandbox.user_bin / "mytool").is_file()
    # Nothing should have landed in the system-wide locations.
    assert not list(sandbox.bin_dir.iterdir())


def test_user_config_paths_are_honoured(sandbox, project):
    # Arbitrary paths, to prove the config is actually read rather than the
    # defaults happening to line up.
    sandbox.write_user_config(
        bin_dir="/etc/dumb_installer/custom_bin",
        install_dir="/etc/dumb_installer/custom_lib",
    )
    for name in ("custom_bin", "custom_lib"):
        (sandbox.etc_dir / name).mkdir(parents=True, exist_ok=True)

    result = sandbox.run([], cwd=project, as_root=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (sandbox.etc_dir / "custom_lib" / "mytool" / "main.py").is_file()
    assert (sandbox.etc_dir / "custom_bin" / "mytool").is_file()


# ===========================================================================
# -C / --init-global-config
# ===========================================================================


def test_global_config_created_for_root(sandbox, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = sandbox.run(["-C"], cwd=empty)
    assert result.returncode == 0
    # separate_sudo_config means root config lives in /etc.
    assert (sandbox.etc_dir / "config.toml").is_file()


def test_global_config_created_for_user(sandbox, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = sandbox.run(["-C"], cwd=empty, as_root=False)
    assert result.returncode == 0
    assert sandbox.user_config_path().is_file()


def test_global_config_is_not_overwritten(sandbox, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    target = sandbox.etc_dir / "config.toml"
    target.write_text("# hand written\n")

    result = sandbox.run(["-C"], cwd=empty)
    assert result.returncode == 0
    assert target.read_text() == "# hand written\n"


# ===========================================================================
# --init family (end to end through the CLI)
# ===========================================================================


def test_init_writes_a_project_build_file(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = sandbox.run(["--init", "mytool", "run-me"], cwd=work)
    assert result.returncode == 0
    build = (work / "dumb_build.toml").read_text()
    assert 'executable_name = "mytool"' in build
    assert 'command = "run-me"' in build


def test_init_does_not_touch_the_global_config(sandbox, tmp_path):
    """Regression: --init used to create the *global* config file instead."""
    work = tmp_path / "work"
    work.mkdir()
    result = sandbox.run(["--init", "mytool", "run-me"], cwd=work)

    assert result.returncode == 0
    assert (work / "dumb_build.toml").is_file()
    assert not (sandbox.etc_dir / "config.toml").exists()
    assert not sandbox.user_config_path().exists()


def test_init_does_not_write_swapped_arguments(sandbox, tmp_path):
    """Regression: the old code unpacked (created, path) and swapped them."""
    work = tmp_path / "work"
    work.mkdir()
    sandbox.run(["--init", "realname", "realcommand"], cwd=work)

    import tomllib

    with (work / "dumb_build.toml").open("rb") as f:
        build = tomllib.load(f)["build"]
    assert build["executable_name"] == "realname"
    assert build["command"] == "realcommand"


def test_init_refuses_to_overwrite(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "dumb_build.toml").write_text("# mine\n")
    result = sandbox.run(["--init", "t", "c"], cwd=work)
    assert result.returncode != 0
    assert (work / "dumb_build.toml").read_text() == "# mine\n"


def test_inite_end_to_end(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (work / "run.sh").chmod(0o644)

    result = sandbox.run(["--inite", "mytool", "run.sh"], cwd=work)
    assert result.returncode == 0
    assert "dumb_project_dir/run.sh" in (work / "dumb_build.toml").read_text()


def test_inite_missing_file_fails(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = sandbox.run(["--inite", "mytool", "nope.sh"], cwd=work)
    assert result.returncode != 0
    assert not (work / "dumb_build.toml").exists()


def test_initp_end_to_end(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "main.py").write_text("print('hi')\n")
    result = sandbox.run(["--initp", "mytool", "main.py"], cwd=work)
    assert result.returncode == 0
    assert "python $dumb_project_dir/main.py" in (work / "dumb_build.toml").read_text()


def test_initr_end_to_end(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "Cargo.toml").write_text('[package]\nname = "mycrate"\n')
    result = sandbox.run(["--initr"], cwd=work)
    assert result.returncode == 0
    build = (work / "dumb_build.toml").read_text()
    assert 'executable_name = "mycrate"' in build
    assert "cargo build --release" in build


# ===========================================================================
# Uninstall
# ===========================================================================


# Uninstall runs in-process rather than in the sandbox. The sandbox backs
# /usr/lib/dumb_builds with a bind mount, and a mount point can never be
# rmdir'd from inside its own mount namespace -- and uninstall always attempts
# that removal when the directory is empty, so it cannot succeed there at all.
# The logic is pure path handling, so it is exercised directly.
#
# See TESTING_PLAN.md section 9 for the resulting gap.


def _fake_config(bin_dir, install_dir):
    from config import Config

    cfg = Config.__new__(Config)
    cfg.binary_dir = bin_dir
    cfg.project_install_dir = install_dir
    return cfg


def test_uninstall_removes_parent_when_empty_inprocess(tmp_path):
    from dumb_installer import uninstall

    bin_dir = tmp_path / "bin"
    lib_dir = tmp_path / "lib"
    bin_dir.mkdir()
    (bin_dir / "mytool").write_text("#!/bin/sh\n")
    (lib_dir / "mytool").mkdir(parents=True)
    (lib_dir / "mytool" / "main.py").write_text("x")

    uninstall(_fake_config(bin_dir, lib_dir), "mytool")

    assert not (bin_dir / "mytool").exists()
    assert not (lib_dir / "mytool").exists()
    assert not lib_dir.exists(), "empty install dir should be removed"


def test_uninstall_keeps_parent_when_others_remain_inprocess(tmp_path):
    from dumb_installer import uninstall

    bin_dir = tmp_path / "bin"
    lib_dir = tmp_path / "lib"
    bin_dir.mkdir()
    (bin_dir / "first").write_text("#!/bin/sh\n")
    (lib_dir / "first").mkdir(parents=True)
    (lib_dir / "second").mkdir()

    uninstall(_fake_config(bin_dir, lib_dir), "first")

    assert lib_dir.exists(), "non-empty install dir must be kept"
    assert (lib_dir / "second").is_dir()
    assert not (bin_dir / "first").exists()


def test_uninstall_unknown_name_exits_inprocess(tmp_path):
    from dumb_installer import uninstall

    with pytest.raises(SystemExit) as excinfo:
        uninstall(_fake_config(tmp_path / "bin", tmp_path / "lib"), "nope")
    assert excinfo.value.code == 1


def test_uninstall_tolerates_missing_wrapper(tmp_path):
    """A half-removed install (wrapper gone, project left) should still work."""
    from dumb_installer import uninstall

    bin_dir = tmp_path / "bin"
    lib_dir = tmp_path / "lib"
    bin_dir.mkdir()
    (lib_dir / "mytool").mkdir(parents=True)

    uninstall(_fake_config(bin_dir, lib_dir), "mytool")

    assert not lib_dir.exists()


def test_uninstall_unknown_program_exits_nonzero(sandbox):
    """Exit-code check only: the sandbox mount makes the full path
    untestable, but an unknown name is rejected before any deletion."""
    result = sandbox.run(["-E", "never-installed"])
    assert result.returncode != 0

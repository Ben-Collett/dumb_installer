"""Phase 4 (init half): the --init family, driven in-process on a real cwd.

These use a real temporary directory rather than the sandbox: every one of
them writes only to the current directory, so no system path is touched.
"""

import os
import stat
from pathlib import Path

import pytest

import build_initializer as bi
from constants import CONFIG_FILE


@pytest.fixture
def in_tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def read_toml(root: Path) -> dict:
    import tomllib

    with (root / CONFIG_FILE).open("rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# create_initial_config
# ---------------------------------------------------------------------------


def test_create_initial_config_writes_required_fields(in_tmp_cwd):
    bi.create_initial_config("mytool", "run-me")
    data = read_toml(in_tmp_cwd)
    assert data["build"]["executable_name"] == "mytool"
    assert data["build"]["command"] == "run-me"


def test_create_initial_config_includes_standard_excludes(in_tmp_cwd):
    bi.create_initial_config("mytool", "run-me")
    build = read_toml(in_tmp_cwd)["build"]
    assert build["local_install_excluded"] == [".git"]
    assert build["remote_install_excluded"] == []


# ---------------------------------------------------------------------------
# create_initial_config_with_exclusions
# ---------------------------------------------------------------------------


def test_create_with_exclusions(in_tmp_cwd):
    bi.create_initial_config_with_exclusions("t", "c", ["*.log", "target"])
    build = read_toml(in_tmp_cwd)["build"]
    assert build["excluded"] == ["*.log", "target"]


def test_create_with_exclusions_empty_list(in_tmp_cwd):
    bi.create_initial_config_with_exclusions("t", "c", [])
    assert read_toml(in_tmp_cwd)["build"]["excluded"] == []


# ---------------------------------------------------------------------------
# create_rust_initial_config
# ---------------------------------------------------------------------------


def test_rust_config_has_build_hooks(in_tmp_cwd):
    bi.create_rust_initial_config("mycrate", "run", [".gitignore"])
    build = read_toml(in_tmp_cwd)["build"]
    assert build["on_install"] == "cargo build --release"
    assert build["on_update"] == "cargo build --release"


# ---------------------------------------------------------------------------
# init_project_config
# ---------------------------------------------------------------------------


def test_init_project_config_writes_file(in_tmp_cwd):
    bi.init_project_config("tool", "cmd here")
    assert (in_tmp_cwd / CONFIG_FILE).is_file()
    build = read_toml(in_tmp_cwd)["build"]
    assert build["executable_name"] == "tool"
    assert build["command"] == "cmd here"


def test_init_project_config_refuses_to_overwrite(in_tmp_cwd):
    (in_tmp_cwd / CONFIG_FILE).write_text("# mine\n")
    with pytest.raises(SystemExit):
        bi.init_project_config("tool", "cmd")
    assert (in_tmp_cwd / CONFIG_FILE).read_text() == "# mine\n"


# ---------------------------------------------------------------------------
# init_project_config_with_executable  (--inite)
# ---------------------------------------------------------------------------


def test_inite_points_command_at_the_file(in_tmp_cwd):
    script = in_tmp_cwd / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    bi.init_project_config_with_executable("mytool", "run.sh")
    build = read_toml(in_tmp_cwd)["build"]
    assert build["executable_name"] == "mytool"
    assert build["command"] == "$dumb_project_dir/run.sh"


def test_inite_makes_the_file_executable(in_tmp_cwd):
    script = in_tmp_cwd / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o644)
    bi.init_project_config_with_executable("mytool", "run.sh")
    assert os.access(script, os.X_OK)


def test_inite_keeps_already_executable_bit(in_tmp_cwd):
    script = in_tmp_cwd / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o755)
    before = script.stat().st_mode
    bi.init_project_config_with_executable("mytool", "run.sh")
    assert script.stat().st_mode == before


def test_inite_missing_file_exits(in_tmp_cwd):
    with pytest.raises(SystemExit):
        bi.init_project_config_with_executable("mytool", "nope.sh")
    assert not (in_tmp_cwd / CONFIG_FILE).exists()


def test_inite_refuses_to_overwrite(in_tmp_cwd):
    script = in_tmp_cwd / "run.sh"
    script.write_text("#!/bin/sh\n")
    (in_tmp_cwd / CONFIG_FILE).write_text("# mine\n")
    with pytest.raises(SystemExit):
        bi.init_project_config_with_executable("mytool", "run.sh")
    assert (in_tmp_cwd / CONFIG_FILE).read_text() == "# mine\n"


# ---------------------------------------------------------------------------
# init_project_config_python  (--initp)
# ---------------------------------------------------------------------------


def test_initp_uses_python_and_sensible_excludes(in_tmp_cwd):
    (in_tmp_cwd / "main.py").write_text("print('hi')\n")
    bi.init_project_config_python("mytool", "main.py")
    build = read_toml(in_tmp_cwd)["build"]
    assert build["command"] == "python $dumb_project_dir/main.py"
    assert "__pycache__" in build["excluded"]
    assert "*.pyc" in build["excluded"]


def test_initp_missing_file_exits(in_tmp_cwd):
    with pytest.raises(SystemExit):
        bi.init_project_config_python("mytool", "nope.py")
    assert not (in_tmp_cwd / CONFIG_FILE).exists()


def test_initp_refuses_to_overwrite(in_tmp_cwd):
    (in_tmp_cwd / "main.py").write_text("print('hi')\n")
    (in_tmp_cwd / CONFIG_FILE).write_text("# mine\n")
    with pytest.raises(SystemExit):
        bi.init_project_config_python("mytool", "main.py")
    assert (in_tmp_cwd / CONFIG_FILE).read_text() == "# mine\n"


# ---------------------------------------------------------------------------
# get_cargo_executable_name
# ---------------------------------------------------------------------------


def test_cargo_name_from_cargo_toml(in_tmp_cwd):
    (in_tmp_cwd / "Cargo.toml").write_text('[package]\nname = "mycrate"\n')
    assert bi.get_cargo_executable_name() == "mycrate"


def test_cargo_name_missing_file(in_tmp_cwd):
    assert bi.get_cargo_executable_name() is None


def test_cargo_name_invalid_toml(in_tmp_cwd):
    (in_tmp_cwd / "Cargo.toml").write_text("not = = toml [[[")
    assert bi.get_cargo_executable_name() is None


def test_cargo_name_missing_package_section(in_tmp_cwd):
    (in_tmp_cwd / "Cargo.toml").write_text('[dependencies]\nserde = "1"\n')
    assert bi.get_cargo_executable_name() is None


# ---------------------------------------------------------------------------
# init_project_config_rust  (--initr)
# ---------------------------------------------------------------------------


def test_initr_uses_cargo_name(in_tmp_cwd):
    (in_tmp_cwd / "Cargo.toml").write_text('[package]\nname = "mycrate"\n')
    bi.init_project_config_rust()
    build = read_toml(in_tmp_cwd)["build"]
    assert build["executable_name"] == "mycrate"
    assert build["command"] == "$dumb_project_dir/target/release/mycrate"
    assert "target" in build["excluded"]


def test_initr_without_cargo_toml_uses_placeholder(in_tmp_cwd):
    bi.init_project_config_rust()
    build = read_toml(in_tmp_cwd)["build"]
    assert build["executable_name"] == "<executable_name>"


def test_initr_refuses_to_overwrite(in_tmp_cwd):
    (in_tmp_cwd / "Cargo.toml").write_text('[package]\nname = "c"\n')
    (in_tmp_cwd / CONFIG_FILE).write_text("# mine\n")
    with pytest.raises(SystemExit):
        bi.init_project_config_rust()
    assert (in_tmp_cwd / CONFIG_FILE).read_text() == "# mine\n"

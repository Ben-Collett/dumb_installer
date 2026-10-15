"""The --add-to-path / --remove-from-path flags.

``env_path`` itself is covered in test_env_path.py; what is asserted here is
the wiring: which directory the flags edit, that they call the right
env_path function, and that off Windows they fail loudly instead of silently
doing nothing. The Windows branch is reached by patching ``sys.platform`` and
swapping the store functions -- this is a unit test of the branch logic, no
real registry is touched (see TESTING_PLAN.md section 9).
"""

import sys

import pytest

import dumb_installer
from config import Config
from dumb_installer import edit_env_path


def make_config(tmp_path) -> Config:
    cfg = Config.__new__(Config)
    cfg.binary_dir = tmp_path / "bin"
    cfg.project_install_dir = tmp_path / "lib"
    return cfg


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


@pytest.fixture
def recorded_calls(monkeypatch):
    """Record what the flags hand to env_path instead of touching a registry."""
    calls = []
    monkeypatch.setattr(
        dumb_installer, "add_path", lambda p: calls.append(("add", p)))
    monkeypatch.setattr(
        dumb_installer, "remove_path", lambda p: calls.append(("remove", p)))
    return calls


# ---------------------------------------------------------------------------
# which directory is edited
# ---------------------------------------------------------------------------


def test_add_edits_the_configured_bin_dir(on_windows, recorded_calls, tmp_path):
    config = make_config(tmp_path)
    edit_env_path(config, present=True)
    assert recorded_calls == [("add", config.binary_dir)]


def test_remove_edits_the_configured_bin_dir(on_windows, recorded_calls, tmp_path):
    config = make_config(tmp_path)
    edit_env_path(config, present=False)
    assert recorded_calls == [("remove", config.binary_dir)]


def test_the_bin_dir_comes_from_config_toml(tmp_path, monkeypatch):
    """A config.toml that pins bin_dir is what decides the entry written,
    so the flag follows the user's config rather than the built-in default."""
    pinned = tmp_path / "somewhere" / "bin"
    config_home = tmp_path / "xdg"
    config_file = config_home / "dumb_installer" / "config.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(f'[paths]\nbin_dir = "{pinned}"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.delenv("SUDO_UID", raising=False)

    config = Config()
    assert config.binary_dir == pinned


# ---------------------------------------------------------------------------
# off windows
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="only applies off windows")
@pytest.mark.parametrize("present", [True, False])
def test_off_windows_it_fails_loudly(present, recorded_calls, tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        edit_env_path(make_config(tmp_path), present=present)
    assert exit_info.value.code == 1
    assert recorded_calls == []
    assert capsys.readouterr().out.strip() != ""


@pytest.mark.skipif(sys.platform == "win32", reason="only applies off windows")
def test_off_windows_the_message_names_the_platform(tmp_path, capsys):
    with pytest.raises(SystemExit):
        edit_env_path(make_config(tmp_path), present=True)
    assert "windows" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# a registry failure is reported, not swallowed
# ---------------------------------------------------------------------------


def test_a_failed_write_exits_nonzero(monkeypatch, on_windows, tmp_path, capsys):
    def explode(_path):
        raise OSError("access denied")

    monkeypatch.setattr(dumb_installer, "add_path", explode)
    with pytest.raises(SystemExit) as exit_info:
        edit_env_path(make_config(tmp_path), present=True)
    assert exit_info.value.code == 1
    assert "access denied" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the flags exist and are wired to the handler
# ---------------------------------------------------------------------------


def test_both_flags_parse():
    args = dumb_installer._make_parser().parse_args(["--add-to-path"])
    assert args.add_to_path and not args.remove_from_path

    args = dumb_installer._make_parser().parse_args(["--remove-from-path"])
    assert args.remove_from_path and not args.add_to_path


def test_the_flags_default_to_off():
    args = dumb_installer._make_parser().parse_args([])
    assert not args.add_to_path
    assert not args.remove_from_path
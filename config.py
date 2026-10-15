from pathlib import Path

from auth import AuthModes
from load_config_map import parse
from constants import (
    DEFAULT_BIN_DIR_ROOT,
    DEFAULT_BIN_DIR_USER,
    DEFAULT_BIN_DIR_USER_WINDOWS,
    DEFAULT_INSTALL_DIR_ROOT,
    DEFAULT_INSTALL_DIR_USER,
    DEFAULT_INSTALL_DIR_USER_WINDOWS,
    PROJECT_NAME,
)
from config_manager import ConfigManager
import os

from platform_utils import is_windows


def is_root() -> bool:
    if is_windows():
        return False
    return bool(os.getenv("SUDO_UID"))


# A TOML basic string reads \ as the start of an escape, so a windows path
# written in verbatim ("C:\Users\Ben\AppData\...") does not parse back: \U and
# \A are not valid escapes and tomllib/tomlkit both reject the file. This is
# what makes the generated config unreadable on the machine that generated it.
_TOML_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_string(value) -> str:
    """Render a value as a TOML basic string, escapes and all.

    Paths on posix contain no backslashes, which is why this never mattered
    there; on windows every separator is one.
    """
    text = str(value)
    return '"' + "".join(
        _TOML_ESCAPES.get(char, char) for char in text
    ) + '"'


def config_path() -> Path:
    return ConfigManager(PROJECT_NAME, separate_sudo_config=True).find_config_file("config.toml")


# toml constants
_PATHS = "paths"
_BIN_DIR = "bin_dir"
_INSTALL_DIR = "project_install_dir"


def default_user_bin_dir():
    """Per-user bin dir for the current platform."""
    if is_windows():
        return DEFAULT_BIN_DIR_USER_WINDOWS
    return DEFAULT_BIN_DIR_USER


def default_user_install_dir():
    """Per-user install dir for the current platform."""
    if is_windows():
        return DEFAULT_INSTALL_DIR_USER_WINDOWS
    return DEFAULT_INSTALL_DIR_USER


def default_bin_dir():
    if is_root():
        return DEFAULT_BIN_DIR_ROOT
    else:
        return default_user_bin_dir()


def default_install_dir():
    if is_root():
        return DEFAULT_INSTALL_DIR_ROOT
    else:
        return default_user_install_dir()


class Config:
    def __init__(self) -> None:
        toml = config_path()
        if toml.exists():
            config = parse(toml) or {}
        else:
            config = {}
        paths = config.get(_PATHS) or {}

        binary_dir_str = paths.get(_BIN_DIR)
        if binary_dir_str:
            self.binary_dir: Path = Path(binary_dir_str)
        else:
            self.binary_dir: Path = default_bin_dir()

        project_install_dir_str = paths.get(_INSTALL_DIR)
        if project_install_dir_str:
            self.project_install_dir: Path = Path(project_install_dir_str)
        else:
            self.project_install_dir: Path = default_install_dir()
        self.on_update_mode: AuthModes = AuthModes.from_str(
            config.get("on_update_auth"))
        self.on_install_mode: AuthModes = AuthModes.from_str(
            config.get("on_install_auth"))

    def create_initial_config(self) -> tuple[bool, Path | None]:
        """
        returns False if path already existed True if it was created
        returns the path of the config
        """
        path = config_path()
        if path.exists():
            return False, path
        lines = [f"[{_PATHS}]",
                 f"{_BIN_DIR} = {_toml_string(self.binary_dir)}",
                 f"{_INSTALL_DIR} = {_toml_string(self.project_install_dir)}"]

        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text("\n".join(lines))

        return True, path

    def executable_path(self, executable: str) -> Path:
        return self.binary_dir/executable

    def install_path(self, executable: str) -> Path:
        return self.project_install_dir/executable

    def __repr__(self):
        return f"Config(project_install_dir={self.project_install_dir}, binary_dir={self.binary_dir})"

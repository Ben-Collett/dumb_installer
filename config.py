from pathlib import Path

from load_config_map import parse
from constants import DEFAULT_BIN_DIR, DEFAULT_INSTALL_ROOT, PROJECT_NAME
from config_manager import ConfigManager


def config_path() -> Path:
    return ConfigManager(PROJECT_NAME, separate_sudo_config=True).find_config_file("config.toml")


# toml constants
_PATHS = "paths"
_BIN_DIR = "bin_dir"
_INSTALL_DIR = "project_install_dir"


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
            self.binary_dir: Path = DEFAULT_BIN_DIR

        project_install_dir_str = paths.get(_INSTALL_DIR)
        if project_install_dir_str:
            self.project_install_dir: Path = Path(project_install_dir_str)
        else:
            self.project_install_dir: Path = DEFAULT_INSTALL_ROOT

    def create_initial_config(self) -> tuple[bool, Path | None]:
        """
        returns False if path already existed True if it was created
        returns the path of the config
        """
        path = config_path()
        if path.exists():
            return False, path
        lines = [f"[{_PATHS}]", f'{_BIN_DIR} = "{self.binary_dir}"', f'{
            _INSTALL_DIR} = "{self.project_install_dir}"']

        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text("\n".join(lines))

        return True, path

    def executable_path(self, executable: str) -> Path:
        return self.binary_dir/executable

    def install_path(self, executable: str) -> Path:
        return self.project_install_dir/executable

    def __repr__(self):
        return f"Config(project_install_dir={self.project_install_dir}, binary_dir={self.binary_dir})"

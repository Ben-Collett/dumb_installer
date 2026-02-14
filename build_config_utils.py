from debug_utils import error
from pathlib import Path
from constants import CONFIG_FILE
from typing import Self
from collection_utils import merge_collections_to_set
import tomllib


def _get_excluded(config: dict) -> list[str]:
    if "excluded" in config:
        return config["excluded"]
    return []


def _get_remote_excluded(config: dict) -> list[str]:
    if "remote_install_excluded" in config:
        return config["remote_install_excluded"]
    return []


def _get_local_exclude(config: dict) -> list[str]:
    if "local_install_excluded" in config:
        return config["local_install_excluded"]
    return []


def _load_config(project_root: Path) -> dict:
    config_path = project_root / CONFIG_FILE
    if not config_path.exists():
        error(f"{CONFIG_FILE} not found in current directory")

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        error(f"failed to parse {CONFIG_FILE}: {e}")

    if "build" not in data:
        error("missing [build] section in dumb_build.toml")

    build = data["build"]

    if "executable_name" not in build:
        error("missing 'executable_name' in [build]")

    if "command" not in build:
        error("missing 'command' in [build]")

    return build


class BuildConfig:

    def __init__(self, path: Path):
        config = _load_config(path)
        self._excluded = _get_excluded(config)
        self._remote_excluded = _get_remote_excluded(config)
        self._local_excluded = _get_local_exclude(config)
        self.executable_name = config["executable_name"]
        self.command = config["command"]

    @staticmethod
    def safe_get_build_config(path: Path) -> Self | None:
        try:
            config = BuildConfig(path)
            return config
        except BaseException:
            return None

    def get_local_excluded_files(self) -> list[str]:
        merged_set = merge_collections_to_set(
            self._excluded, self._local_excluded)

        return list(merged_set)

    def get_remote_excluded_files(self) -> list[str]:
        merged_set = merge_collections_to_set(
            self._excluded, self._remote_excluded)
        return list(merged_set)


def safe_get_build_config(path) -> BuildConfig | None:
    pass

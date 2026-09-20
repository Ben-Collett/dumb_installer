from pathlib import Path
from constants import CONFIG_FILE
from collection_utils import merge_collections_to_set
import tomllib

from merged_error import MergedError


def _load_config(project_root: Path) -> dict:
    # just to suppress the warning that data might be unbound after the try, except
    data = {}
    config_path = project_root / CONFIG_FILE

    error = MergedError()
    error.add_error_if(not config_path.exists(), f"{
                       CONFIG_FILE} not found in current directory")

    error.print_and_exit_if_erred()

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        error.add_error(f"failed to parse {CONFIG_FILE}: {e}")
        error.print_and_exit_if_erred()

    error.add_error_if("build" not in data,
                       "missing [build] section in dumb_build.toml")

    error.print_and_exit_if_erred()

    build = data["build"]

    error.on_missing_toml_field("executable_name", "build", build)
    error.on_missing_toml_field("command", "build", build)
    error.print_and_exit_if_erred()

    return build


class BuildConfig:

    def __init__(self, path: Path):
        config = _load_config(path)
        self._excluded: list[str] = config.get("excluded", [])
        self._remote_excluded: list[str] = config.get(
            "remote_install_excluded", [])
        self._local_excluded: list[str] = config.get(
            "local_install_excluded", [])

        self.on_install: str | None = config.get("on_install")
        self.on_update: str | None = config.get("on_update")
        if "executable_name" not in config:
            raise Exception("required property executable name missing")
        self.executable_name: str = config["executable_name"]
        self.command: str = config["command"]

    @staticmethod
    def safe_get_build_config(path: Path) -> "BuildConfig | None":
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

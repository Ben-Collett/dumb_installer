import os
import stat
import tomllib
from constants import CONFIG_FILE
from debug_utils import error
from log_utils import print_info
from pathlib import Path


def create_initial_config(executable_name: str, command: str) -> None:
    config_content = f'''[build]
executable_name = "{executable_name}"
command = "{command}"
excluded = [".gitignore"]
local_install_excluded = [".git"]
remote_install_excluded = []
'''
    Path("dumb_build.toml").write_text(config_content)


def create_initial_config_with_exclusions(
    executable_name: str, command: str, excluded: list[str]
) -> None:
    excluded_str = ", ".join(f'"{e}"' for e in excluded)
    config_content = f'''[build]
executable_name = "{executable_name}"
command = "{command}"
excluded = [{excluded_str}]
local_install_excluded = [".git"]
remote_install_excluded = []
'''
    Path("dumb_build.toml").write_text(config_content)


def create_rust_initial_config(
    executable_name: str, command: str, excluded: list[str]
) -> None:
    excluded_str = ", ".join(f'"{e}"' for e in excluded)
    config_content = f'''[build]
executable_name = "{executable_name}"
command = "{command}"
excluded = [{excluded_str}]
local_install_excluded = [".git"]
remote_install_excluded = []
on_install = "cargo build --release"
on_update = "cargo build --release"
'''
    Path("dumb_build.toml").write_text(config_content)


def init_project_config(path, command):
    config_path = Path("dumb_build.toml")
    if config_path.exists():
        error(f"{CONFIG_FILE} already exists in current directory")
    create_initial_config(path, command)
    print_info(f"Created dumb_build.toml with command='{
        command}'")


def init_project_config_with_executable(command_name, file_path):

    config_path = Path("dumb_build.toml")
    if config_path.exists():
        error(f"{CONFIG_FILE} already exists in current directory")
    file = Path(file_path)
    if not file.exists():
        error(f"file '{file_path}' does not exist")
    command = f"$dumb_project_dir/{file_path}"
    create_initial_config(command_name, command)
    if not os.access(file, os.X_OK):
        file.chmod(
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )
        print_info(f"Created dumb_build.toml and made '{
                   file_path}' executable")
    else:
        print_info(f"Created dumb_build.toml with executable_name='{
            command_name}'")


def init_project_config_python(command_name, python_file):
    config_path = Path("dumb_build.toml")
    if config_path.exists():
        error(f"{CONFIG_FILE} already exists in current directory")
    file = Path(python_file)
    if not file.exists():
        error(f"python file '{python_file}' does not exist")
    command = f"python $dumb_project_dir/{python_file}"
    excluded = [".gitignore", "__pycache__", "*.pyc", ".ruff_cache"]
    create_initial_config_with_exclusions(command_name, command, excluded)
    print_info(f"Created dumb_build.toml for Python project '{command_name}'")


def get_cargo_executable_name() -> str | None:
    cargo_path = Path("Cargo.toml")
    if not cargo_path.exists():
        return None
    try:
        with cargo_path.open("rb") as f:
            data = tomllib.load(f)
        return data.get("package", {}).get("name")
    except (OSError, tomllib.TOMLDecodeError):
        return None


def init_project_config_rust():
    config_path = Path("dumb_build.toml")
    if config_path.exists():
        error(f"{CONFIG_FILE} already exists in current directory")

    executable_name = get_cargo_executable_name() or "<executable_name>"
    command = f"$dumb_project_dir/target/release/{executable_name}"
    excluded = [".gitignore", "LICENSE*", "README*", "target"]
    create_rust_initial_config(executable_name, command, excluded)
    print_info(f"Created dumb_build.toml for Rust project '{
        executable_name}'")
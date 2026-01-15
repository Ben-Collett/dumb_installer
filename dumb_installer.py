#!/usr/bin/env python3

import os
import sys
import shutil
import stat
import tomllib
from pathlib import Path
import argparse

# TODO: allow user to override install locations, maybe  do a separate user_space vs system install
# using ~/.local/bin and I don't kkow what for the opt mayble local state?
DEFAULT_INSTALL_ROOT = Path("/opt/dumb_builds")
DEFAULT_BIN_DIR = Path("/usr/local/bin")
CONFIG_FILE = "dumb_build.toml"
SHABANG = "#!/usr/bin/env sh"


def error(msg: str) -> None:
    print(f"dumb_builder error: {msg}", file=sys.stderr)
    sys.exit(1)


def require_root() -> None:
    if os.geteuid() != 0:
        error("must be run as root")


def load_config(project_root: Path) -> dict:
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


def copy_project(src: Path, dest: Path, exclude) -> None:
    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(
        src,
        dest,
        symlinks=True,
        ignore=shutil.ignore_patterns(*exclude),
    )


def write_wrapper(executable_name: str, command: str, project_dir: Path, bin_dir: Path):
    bin_dir.mkdir(parents=True, exist_ok=True)

    wrapper_path = bin_dir / executable_name

    script = f'{SHABANG}\ndumb_project_dir={project_dir}\n{command} $@'

    wrapper_path.write_text(script)
    wrapper_path.chmod(
        stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |
        stat.S_IRGRP | stat.S_IXGRP |
        stat.S_IROTH | stat.S_IXOTH
    )


def delete_from_path(p: Path):
    if p.is_file() or p.is_symlink():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


def is_empty_dir(p: Path):
    return p.exists() and p.is_dir() and not any(p.iterdir())


def main() -> None:

    parser = argparse.ArgumentParser(
        prog="dumb installer", description="easy way to install programs system wide on linux, from scripts. Without having to deal with package managers")

    # TODO add support for these options:
    # parser.add_argument("-u", "--user_install", action='store_true')
    # parser.add_argument("-U", "--uninstall", action='store_true')

    parser.add_argument("-E", "--exe-uninstall", type=str)

    require_root()

    args = parser.parse_args()

    if args.exe_uninstall:
        bin_path = DEFAULT_BIN_DIR / args.exe_uninstall
        dumb_path = DEFAULT_INSTALL_ROOT / args.exe_uninstall

        if bin_path.exists():
            print("deleting", bin_path)
            delete_from_path(bin_path)
        if dumb_path.exists():
            print("deleting", bin_path)
            delete_from_path(dumb_path)

        if is_empty_dir(DEFAULT_INSTALL_ROOT):
            delete_from_path(DEFAULT_INSTALL_ROOT)
            print(f"no programs left in {DEFAULT_INSTALL_ROOT}, deleting")

        exit()
    project_root = Path.cwd().resolve()
    build = load_config(project_root)

    executable_name = build["executable_name"]
    command = build["command"]
    if "exclude" in build.keys():
        exclude = build["exclude"]
    else:
        exclude = ["__pycache__", "*.pyc", ".git", "dumb_build.toml"]

    DEFAULT_INSTALL_ROOT.mkdir(parents=True, exist_ok=True)

    bin_dir = DEFAULT_BIN_DIR
    install_dir = DEFAULT_INSTALL_ROOT / executable_name

    copy_project(project_root, install_dir, exclude)
    write_wrapper(executable_name, command, install_dir, bin_dir)

    print(f"Installed '{executable_name}' system-wide")
    print(f"Project location: {install_dir}")
    print(f"Executable: {DEFAULT_BIN_DIR / executable_name}")


if __name__ == "__main__":
    main()

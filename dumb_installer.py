import os
import shutil
import stat
from debug_utils import error
from pathlib import Path
import argparse
from build_config_utils import BuildConfig
from file_utils import directories_differ, copy_project, remove_excluded
from git_wrapper import GitWrapper
from constants import SHABANG, METADATA_FILE, DEFAULT_INSTALL_ROOT
from constants import DEFAULT_BIN_DIR, CONFIG_FILE, GIT_CLONE_DIR
from meta_data import MetaData

# TODO: allow user to override install locations, maybe  do a separate user_space vs system install
# using ~/.local/bin and I don't kkow what for the opt mayble local state?


def require_root() -> None:
    if os.geteuid() != 0:
        error("must be run as root")


def write_wrapper(executable_name: str, command: str, project_dir: Path, bin_dir: Path):
    bin_dir.mkdir(parents=True, exist_ok=True)

    wrapper_path = bin_dir / executable_name

    script = f'{SHABANG}\ndumb_project_dir={project_dir}\n{command} "$@"'

    wrapper_path.write_text(script)
    wrapper_path.chmod(
        stat.S_IRUSR
        | stat.S_IWUSR
        | stat.S_IXUSR
        | stat.S_IRGRP
        | stat.S_IXGRP
        | stat.S_IROTH
        | stat.S_IXOTH
    )


def delete_from_path(p: Path):
    if not p.exists():
        return
    elif p.is_file() or p.is_symlink():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


def filter_out_git_affecting_patterns(patterns: list[str]):
    out = []
    for p in patterns:
        if ".git/" in p:
            continue
        if p == ".git":
            continue

        out.append(p)

    return out


def is_empty_dir(p: Path):
    return p.exists() and p.is_dir() and not any(p.iterdir())


def update_executable(executable_name: str) -> None:
    print(f"Updating {executable_name}...")
    install_dir = DEFAULT_INSTALL_ROOT / executable_name
    if not install_dir.exists():
        print(f"Failed: couldn't find source directory at {install_dir}")
        return

    meta_data = MetaData().update_from(install_dir)
    is_git = meta_data.is_git_install

    if is_git:
        git_wrapper = GitWrapper()
        result = git_wrapper.updateRepoAtPath(install_dir)
        if not result.success:
            if "already up to date" in result.failureMessage:
                print("already up to date")
            else:
                print(f"Failed to update: {result.failureMessage}")
        else:
            # incase something was added or deleted from the excluded section's

            build = BuildConfig.safe_get_build_config(install_dir)

            if build:
                remove_excluded(install_dir, build.get_remote_excluded_files())
            else:
                print("no build file found during update")

            print("updated")
        return

    source_dir = meta_data.source_path
    if source_dir is None:
        print("No source directory path")
        return

    if not source_dir.exists():
        print(f"Failed: couldn't find source directory at {source_dir}")
        return

    if not (source_dir / CONFIG_FILE).exists():
        print(f"Failed: couldn't find source directory at {source_dir}")
        return

    build = BuildConfig(source_dir)

    exclude = build.get_local_excluded_files()
    # add the metadata file for the directoires_differ cal
    exclude.append(METADATA_FILE)
    if not directories_differ(install_dir, source_dir, exclude):
        print("already up to date")
        return

    copy_project(source_dir, install_dir, exclude)
    data = MetaData(is_git_install=is_git, source_path=source_dir)
    data.write(install_dir)
    print("updated")


def update_all() -> None:
    if not DEFAULT_INSTALL_ROOT.exists():
        return

    for entry in DEFAULT_INSTALL_ROOT.iterdir():
        if entry.is_dir():
            update_executable(entry.name)


def is_required_by_git(pattern):
    pass


def main() -> None:

    parser = argparse.ArgumentParser(
        prog="dumb installer",
        description="easy way to install programs system wide on linux, from scripts. Without having to deal with package managers",
    )

    # TODO add support for these options:
    # parser.add_argument("-u", "--user_install", action='store_true')
    # parser.add_argument("-U", "--uninstall", action='store_true')

    parser.add_argument("-E", "--exe-uninstall", type=str)
    parser.add_argument(
        "-n", "--name", type=str, help="Override the executable name from config"
    )
    parser.add_argument("--update", type=str,
                        help="Update a specific executable")
    parser.add_argument(
        "--update-all", action="store_true", help="Update all installed executables"
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="Git repository URL to install from",
    )

    require_root()

    args = parser.parse_args()

    if args.exe_uninstall:
        bin_path = DEFAULT_BIN_DIR / args.exe_uninstall
        dumb_path = DEFAULT_INSTALL_ROOT / args.exe_uninstall

        if not bin_path.exists() and not dumb_path.exists():
            print("program not found terminating.")
            exit(1)
        if bin_path.exists():
            print("deleting", bin_path)
            delete_from_path(bin_path)
        if dumb_path.exists():
            print("deleting", dumb_path)
            delete_from_path(dumb_path)

        if is_empty_dir(DEFAULT_INSTALL_ROOT):
            delete_from_path(DEFAULT_INSTALL_ROOT)
            print(f"no programs left in {DEFAULT_INSTALL_ROOT}, deleting")

        exit()

    if args.update:
        update_executable(args.update)
        exit()

    if args.update_all:
        update_all()
        exit()

    is_git_install = args.url
    if is_git_install:
        git_wrapper = GitWrapper()
        if not git_wrapper.is_git_installed():
            error("Git is not installed or not available in PATH")

        GIT_CLONE_DIR.mkdir(parents=True, exist_ok=True)
        temp_clone_path = GIT_CLONE_DIR / f"temp_clone_{os.getpid()}"
        clone_result = git_wrapper.cloneTo(args.url, str(temp_clone_path))
        if not clone_result.success:
            print(f"Failed to clone repository: {clone_result.failureMessage}")
            delete_from_path(temp_clone_path)
            exit(1)

        project_root = temp_clone_path.resolve()

        try:
            build = BuildConfig(project_root)
        except SystemExit:
            print("Failed to install: could not load config from cloned repository")
            delete_from_path(temp_clone_path)
            exit(1)
    else:
        project_root = Path.cwd().resolve()
        build = BuildConfig(project_root)

    executable_name = build.executable_name
    command = build.command
    if args.name:
        executable_name = args.name

    if is_git_install:
        exclude = build.get_remote_excluded_files()
    else:
        exclude = build.get_local_excluded_files()

    DEFAULT_INSTALL_ROOT.mkdir(parents=True, exist_ok=True)

    bin_dir = DEFAULT_BIN_DIR
    install_dir = DEFAULT_INSTALL_ROOT / executable_name

    copy_project(project_root, install_dir, exclude)
    MetaData(is_git_install=is_git_install,
             source_path=project_root).write(install_dir)
    write_wrapper(executable_name, command, install_dir, bin_dir)

    print(f"Installed '{executable_name}' system-wide")
    print(f"Project location: {install_dir}")
    print(f"Executable: {DEFAULT_BIN_DIR / executable_name}")


if __name__ == "__main__":
    main()

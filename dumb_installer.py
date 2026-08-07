import os
import shutil
import stat
from config import Config, is_root
from debug_utils import error
from pathlib import Path
import argparse
from build_config_utils import BuildConfig
from file_utils import directories_differ, copy_project, remove_excluded
from git_wrapper import GitWrapper
from constants import SHABANG, METADATA_FILE
from constants import CONFIG_FILE, GIT_CLONE_DIR
from meta_data import MetaData

# TODO: allow user to override install locations, maybe  do a separate user_space vs system install
# using ~/.local/bin and I don't kkow what for the opt mayble local state?


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


def update_executable(config: Config, executable_name: str) -> None:
    print(f"Updating {executable_name}...")
    install_dir = config.install_path(executable_name)
    if not install_dir.exists():
        print(f"Failed: couldn't find source directory at {install_dir}")
        return

    meta_data = MetaData().update_from(install_dir)
    is_git = meta_data.is_git_install

    if is_git:
        git_wrapper = GitWrapper()
        result = git_wrapper.updateRepoAtPath(install_dir)
        if not result.success:
            if result.failureMessage and "already up to date" in result.failureMessage:
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


def projects(project_dir: Path):
    if not project_dir.exists():
        return

    for project in project_dir.iterdir():
        if project.is_dir():
            yield project


def update_all(config: Config) -> None:
    for project in projects(config.project_install_dir):
        update_executable(config, project.name)


def uninstall(user_config: Config, name):

    bin_path = user_config.binary_dir / name
    dumb_path = user_config.project_install_dir / name

    if not bin_path.exists() and not dumb_path.exists():
        print("program not found terminating.")
        exit(1)
    if bin_path.exists():
        print("deleting", bin_path)
        delete_from_path(bin_path)
    if dumb_path.exists():
        print("deleting", dumb_path)
        delete_from_path(dumb_path)

    install_path = user_config.project_install_dir
    if is_empty_dir(install_path):
        delete_from_path(install_path)
        print(f"no programs left in {install_path}, deleting")


def main() -> None:
    user_config = Config()

    parser = argparse.ArgumentParser(
        prog="dumb installer",
        description="easy way to install programs system-wide or per user on linux, from scripts. Without having to deal with package managers",
    )

    # TODO add support for these options:
    # parser.add_argument("-u", "--user_install", action='store_true')
    parser.add_argument("-C", "--init-global-config", action='store_true',
                        help="creates a dumb installer config for the current user if sudo /etc/dumb_installer/config.toml if a regular user then the config direction dumb_installer/config.toml")

    parser.add_argument("-E", "--exe-uninstall", type=str)
    parser.add_argument(
        "-n", "--name", type=str, help="Override the executable name from config"
    )
    parser.add_argument("--update", type=str,
                        help="Update a specific executable")
    parser.add_argument(
        "--update-all", action="store_true", help="Update all installed executables"
    )
    parser.add_argument("--init", nargs=2, metavar=("EXECUTABLE_NAME", "COMMAND"),
                        help="Create a minimal dumb_build.toml in current directory")
    parser.add_argument("--inite", nargs=2, metavar=("COMMAND_NAME", "FILE"),
                        help="Create dumb_build.toml with command pointing to executable file")
    parser.add_argument("--initp", nargs=2, metavar=("COMMAND_NAME", "PYTHON_FILE"),
                        help="Create dumb_build.toml for Python project")
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="Git repository URL to install from",
    )

    args = parser.parse_args()

    if args.init_global_config:
        created, path = user_config.create_initial_config()
        if created:
            print("created config at", path)
        else:
            print("user config already existed at", path)
        exit()

    if args.init:
        executable_name, command = args.init
        config_path = Path("dumb_build.toml")
        if config_path.exists():
            error(f"{CONFIG_FILE} already exists in current directory")
            exit()
        create_initial_config(executable_name, command)
        print(f"Created dumb_build.toml with executable_name='{
              executable_name}'")
        exit()

    if args.inite:
        command_name, file_path = args.inite
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
            print(f"Created dumb_build.toml and made '{file_path}' executable")
        else:
            print(f"Created dumb_build.toml with executable_name='{
                  command_name}'")
        exit()

    if args.initp:
        command_name, python_file = args.initp
        config_path = Path("dumb_build.toml")
        if config_path.exists():
            error(f"{CONFIG_FILE} already exists in current directory")
        file = Path(python_file)
        if not file.exists():
            error(f"python file '{python_file}' does not exist")
        command = f"python $dumb_project_dir/{python_file}"
        excluded = [".gitignore", "__pycache__", "*.pyc", ".ruff_cache"]
        create_initial_config_with_exclusions(command_name, command, excluded)
        print(f"Created dumb_build.toml for Python project '{command_name}'")
        exit()

    if args.exe_uninstall:
        uninstall(user_config, args.exe_uninstall)
        exit()

    if args.update:
        update_executable(user_config, args.update)
        exit()

    if args.update_all:
        update_all(user_config)
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

    user_config.project_install_dir.mkdir(parents=True, exist_ok=True)

    bin_dir = user_config.binary_dir
    install_dir = user_config.project_install_dir / executable_name

    copy_project(project_root, install_dir, exclude)
    MetaData(is_git_install=is_git_install,
             source_path=project_root).write(install_dir)
    write_wrapper(executable_name, command, install_dir, bin_dir)

    if is_root():
        print(f"Installed '{executable_name}' system-wide")
    else:
        print(f"Installed '{executable_name}' for user")

    print(f"Project location: {install_dir}")
    print(f"Executable: {user_config.binary_dir / executable_name}")


if __name__ == "__main__":
    main()

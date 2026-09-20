import os
import shutil
import stat
from auth import AuthModes
from config import Config, is_root
from debug_utils import error
from pathlib import Path
import argparse
from build_config_utils import BuildConfig
from file_utils import directories_differ, copy_project, remove_excluded
from git_wrapper import GitWrapper
from constants import SHABANG, METADATA_FILE
from constants import CONFIG_FILE, GIT_CLONE_DIR
from hook_failure_types import HookFailure, HookResult,  HookSuccess
from log_utils import print_error, print_info, print_warning
from meta_data import MetaData
from process_wrapper import ProcessWrapper
from snapshot import Snapshot
from user_prompt import UserPrompt


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


def authenticate_can_run_hook(auth_mode: AuthModes, hook_name, executable_name, user_prompt=UserPrompt()):
    if auth_mode == AuthModes.AUTO_REJECT:
        return False
    if auth_mode == AuthModes.AUTO_APPROVE:
        return True
    return user_prompt.yes_or_no_prompt(f"allow program {executable_name} to run {hook_name} hook")


def authenticate_can_run_on_update(config: Config, executable_name: str, user_prompt=UserPrompt()):
    return authenticate_can_run_hook(config.on_update_mode, "on_update", executable_name, user_prompt)


def authenticate_can_run_on_install(config: Config, executable_name: str, user_prompt=UserPrompt()):
    return authenticate_can_run_hook(config.on_install_mode, "on_install", executable_name, user_prompt)


def safe_run_on_update_hook(config: Config, build_config: BuildConfig, process_wrapper: ProcessWrapper) -> HookResult:
    if build_config.on_update is not None:
        if not authenticate_can_run_on_update(config, build_config.executable_name):
            return HookFailure("update failed, couldn't run on_update hook, reverting... ")
        res = process_wrapper.run_in_dir(build_config.on_update)
        if res != 0:
            return HookFailure("on_update hook returned a non 0 status code, reverting... ")
    return HookSuccess()


def safe_run_on_install_hook(config: Config, build_config: BuildConfig, process_wrapper: ProcessWrapper) -> HookResult:
    if build_config.on_update is not None:
        if not authenticate_can_run_on_install(config, build_config.executable_name):
            return HookFailure("install failed, couldn't run on_install hook, removing... ")
        if process_wrapper.run_in_dir(build_config.on_install) != 0:
            return HookFailure("on_install hook returned a non 0 status code, removing... ")
    return HookSuccess()


def update_executable(config: Config, executable_name: str) -> None:
    print_info(f"Updating {executable_name}...")
    install_dir = config.install_path(executable_name)
    if not install_dir.exists():
        print_error(f"Failed: couldn't find source directory at {install_dir}")
        return

    meta_data = MetaData().update_from(install_dir)
    is_git = meta_data.is_git_install

    if is_git:
        git_wrapper = GitWrapper()
        git_wrapper.full_stash(install_dir)
        result = git_wrapper.updateRepoAtPath(install_dir)

        if not result.success:
            if result.failureMessage and "already up to date" in result.failureMessage:
                print_info("already up to date")
            else:
                print_error(f"Failed to update: {result.failureMessage}")
        else:
            # incase something was added or deleted from the excluded section's

            build = BuildConfig.safe_get_build_config(install_dir)

            if build is not None:

                hook_result = safe_run_on_update_hook(
                    config, build, ProcessWrapper(install_dir))
                if not hook_result.success():
                    print_error(f"update failed for {
                        build.executable_name} reverting...")
                    git_wrapper.pop_stash(install_dir)
                    print_info(hook_result.get_message())
                    return
                remove_excluded(install_dir, build.get_remote_excluded_files())
            else:
                print_warning("no build file found during update")

            print_info("updated")
        git_wrapper.clear_stash(install_dir)
        return

    source_dir = meta_data.source_path
    if source_dir is None:
        print_error("No source directory path")
        return

    if not source_dir.exists():
        print_error(f"Failed: couldn't find source directory at {source_dir}")
        return

    if not (source_dir / CONFIG_FILE).exists():
        print_error(f"Failed: couldn't find source directory at {source_dir}")
        return

    build = BuildConfig(source_dir)

    exclude = build.get_local_excluded_files()
    # add the metadata file for the directoires_differ cal
    exclude.append(METADATA_FILE)
    if not directories_differ(install_dir, source_dir, exclude):
        print_info("already up to date")
        return

    snap_shot = Snapshot(install_dir)
    copy_project(source_dir, install_dir, exclude)
    res = safe_run_on_update_hook(config, build, ProcessWrapper(install_dir))
    if not res.success():
        print_error(f"update for {build.executable_name} failed, reverting...")
        snap_shot.revert_and_discard()
        print_error("update failed because:")
        print_error(res.get_message())
        return

    snap_shot.discard()
    data = MetaData(is_git_install=is_git, source_path=source_dir)
    data.write(install_dir)
    print_info("updated")


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
        print_info("program not found terminating.")
        exit(1)
    if bin_path.exists():
        print_info("deleting", bin_path)
        delete_from_path(bin_path)
    if dumb_path.exists():
        print_info("deleting", dumb_path)
        delete_from_path(dumb_path)

    install_path = user_config.project_install_dir
    if is_empty_dir(install_path):
        delete_from_path(install_path)
        print_info(f"no programs left in {install_path}, deleting")


def _make_parser() -> argparse.ArgumentParser:

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
    return parser


def _create_initial_config(user_config: Config):
    created, path = user_config.create_initial_config()
    if created:
        print_info("created config at", path)
    else:
        print_warning("user config already existed at", path)


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


def main() -> None:
    user_config = Config()

    args = _make_parser().parse_args()

    if args.init_global_config:
        _create_initial_config(user_config)
        exit()

    if args.init:
        command, path = user_config.create_initial_config()

        # init project config can also exit if the file already exist.
        # or there is an io error
        init_project_config(command, path)
        exit()

    if args.inite:
        command_name, file_path = args.inite
        init_project_config_with_executable(command_name, file_path)
        exit()

    if args.initp:
        command_name, python_file = args.initp
        init_project_config_python(command_name, python_file)
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
            print_error(f"Failed to clone repository: {
                        clone_result.failureMessage}")
            delete_from_path(temp_clone_path)
            exit(1)

        project_root = temp_clone_path.resolve()

        try:
            build = BuildConfig(project_root)
        except SystemExit:
            print_error(
                "Failed to install: could not load config from cloned repository")
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

    if is_git_install:
        shutil.rmtree(project_root)

    res = safe_run_on_install_hook(
        user_config, build, ProcessWrapper(install_dir))
    if not res.success():
        print_info("on install hook failed")
        shutil.rmtree(install_dir)
        print_info(res.get_message())
        exit(1)

    write_wrapper(executable_name, command, install_dir, bin_dir)

    if is_root():
        print_info(f"Installed '{executable_name}' system-wide")
    else:
        print_info(f"Installed '{executable_name}' for user")

    print_info(f"Project location: {install_dir}")
    print_info(f"Executable: {user_config.binary_dir / executable_name}")


if __name__ == "__main__":
    main()

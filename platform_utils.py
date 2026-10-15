import sys

# Windows will not run a file whose name carries no executable extension:
# cmd resolves a command by scanning PATH for each PATHEXT extension, so a
# bare "din" is invisible no matter what the file contains. Linux and macOS
# have no such rule -- a #!/usr/bin/env sh file is runnable as-is -- so the
# suffix stays empty there.
WINDOWS_WRAPPER_SUFFIX = ".cmd"


def is_windows() -> bool:
    return sys.platform == "win32"


def wrapper_filename(executable_name: str) -> str:
    """The wrapper file name to use for executable_name on this platform.

    Everything that creates, removes or prints the wrapper has to agree on
    this, or the installer writes one name and the uninstaller looks for
    another.
    """
    if is_windows():
        return executable_name + WINDOWS_WRAPPER_SUFFIX
    return executable_name

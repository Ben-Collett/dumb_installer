import os
from pathlib import Path
import shutil
import subprocess

from platform_utils import is_windows


# git and the hook commands speak the platform's byte encoding, but there is
# no guarantee it is utf-8. Decoding strictly turns a stray non-ascii byte in
# an error message into a crash, and the message is the only thing the caller
# has to report, so bad bytes become replacement characters instead.
_ENCODING = "utf-8"
_ERRORS = "replace"


class ProcessWrapper:
    def __init__(self, dir: Path | None = None):
        self.dir = dir

    def run_in_dir(self, command: str, dir_override: Path | None = None) -> int:
        dir = dir_override
        if dir is None:
            dir = self.dir
        assert dir is not None, "run in dir called with no dir set"
        return self.run(self.in_dir_command(command, dir))

    @staticmethod
    def in_dir_command(command: str, dir: Path) -> str:
        """The shell line that runs command with dir as the working directory.

        ``cd /d`` is also needed on windows: without ``/d``, ``cd`` only
        changes the directory of the current drive, so a hook on another drive
        """
        if is_windows():
            return f'cd /d "{dir}" && {command}'
        return f'cd "{dir}" && {command}'

    def run(self, command) -> int:
        return os.system(command)

    def run_subprocess(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args, capture_output=True, encoding=_ENCODING, errors=_ERRORS)

    def run_subprocess_in_dir(self, args: list[str], dir_override: Path | None) -> subprocess.CompletedProcess[str]:
        dir = dir_override
        if dir is None:
            dir = self.dir
        assert dir is not None, "run in dir called with no dir set"
        return subprocess.run(
            args, cwd=str(dir.resolve()),
            capture_output=True, encoding=_ENCODING, errors=_ERRORS)

    def has_command(self, cmd: str) -> bool:
        return shutil.which(cmd) is not None

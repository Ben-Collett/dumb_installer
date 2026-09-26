import os
from pathlib import Path
import shutil
import subprocess


class ProcessWrapper:
    def __init__(self, dir: Path | None = None):
        self.dir = dir

    def run_in_dir(self, command: str, dir_override: Path | None = None) -> int:
        dir = dir_override
        if dir is None:
            dir = self.dir
        assert dir is not None, "run in dir called with no dir set"
        return self.run(f"cd {self.dir}; {command}")

    def run(self, command) -> int:
        return os.system(command)

    def run_subprocess(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, text=True, capture_output=True)

    def run_subprocess_in_dir(self, args: list[str], dir_override: Path | None) -> subprocess.CompletedProcess[str]:
        dir = dir_override
        if dir is None:
            dir = self.dir
        assert dir is not None, "run in dir called with no dir set"
        return subprocess.run(args, cwd=str(dir.resolve()), text=True, capture_output=True)

    def has_command(self, cmd: str) -> bool:
        return shutil.which(cmd) is not None

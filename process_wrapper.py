import os
from pathlib import Path


class ProcessWrapper:
    def __init__(self, dir: Path):
        self.dir = dir

    def run_in_dir(self, command):
        return os.system(f"cd {self.dir}; {command}")

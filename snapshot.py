from pathlib import Path
import shutil
import tempfile


class Snapshot:
    def __init__(self, source: Path):
        self.source_path = source
        self.snapshot_path: Path = Path(
            tempfile.mkdtemp(prefix="dumb_installer_snapshot-"))

        shutil.copytree(source, self.snapshot_path,
                        symlinks=True, dirs_exist_ok=True)
        self.discarded = False

    def revert_and_discard(self):
        self.revert()
        self.discard()

    def revert(self):
        if self.discarded:
            raise Exception("can't revert already discarded snapshot")
        shutil.rmtree(self.source_path)
        shutil.copytree(self.snapshot_path, self.source_path, symlinks=True)

    def discard(self):
        if self.discarded:
            raise Exception("can't discard already discarded snapshot")

        self.discarded = True
        shutil.rmtree(self.snapshot_path)

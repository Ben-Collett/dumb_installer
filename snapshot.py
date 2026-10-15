from pathlib import Path
import tempfile

from file_utils import copy_tree, rmtree


class Snapshot:
    def __init__(self, source: Path):
        self.source_path = source
        self.snapshot_path: Path = Path(
            tempfile.mkdtemp(prefix="dumb_installer_snapshot-"))

        copy_tree(source, self.snapshot_path, dirs_exist_ok=True)
        self.discarded = False

    def revert_and_discard(self):
        self.revert()
        self.discard()

    def revert(self):
        if self.discarded:
            raise Exception("can't revert already discarded snapshot")
        rmtree(self.source_path)
        copy_tree(self.snapshot_path, self.source_path)

    def discard(self):
        if self.discarded:
            raise Exception("can't discard already discarded snapshot")

        self.discarded = True
        rmtree(self.snapshot_path)

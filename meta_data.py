import json
from pathlib import Path
from constants import METADATA_FILE
from typing import Self


# meta data is stored as a json file at project_root/METADATA_FILE
class MetaData:
    def __init__(self, is_git_install: bool = False, source_path: Path = None):
        self.is_git_install = is_git_install
        if is_git_install:
            self.source_path = None
        else:
            self.source_path = source_path

    def write(self, project_root: Path) -> Self:
        metadata_path = project_root / METADATA_FILE

        data = {
            "is_git_install": self.is_git_install,
            "source_path": str(self.source_path) if self.source_path else None,
        }

        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
        return self

    def update_from(self, project_root: Path) -> Self:
        """
        Updates current metadata object with the metadata from the project.
        """
        metadata_path = project_root / METADATA_FILE

        if not metadata_path.exists():
            raise FileNotFoundError(
                f"Metadata file not found at {metadata_path}")

        with metadata_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self.is_git_install = data.get("is_git_install", False)

        source_path = data.get("source_path")
        if self.is_git_install:
            self.source_path = None
        else:
            self.source_path = Path(source_path) if source_path else None
        return self

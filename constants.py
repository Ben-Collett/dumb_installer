import tempfile
from pathlib import Path
DEFAULT_INSTALL_DIR_ROOT = Path("/usr/lib/dumb_builds")
DEFAULT_BIN_DIR_ROOT = Path("/usr/local/bin")
DEFAULT_BIN_DIR_USER = Path("~/.local/bin").expanduser()
DEFAULT_INSTALL_DIR_USER = Path("~/.local/lib/dumb_builds").expanduser()
DEFAULT_BIN_DIR_USER_WINDOWS = Path(
    "~/AppData/Local/dumb_installer/bin").expanduser()
DEFAULT_INSTALL_DIR_USER_WINDOWS = Path(
    "~/AppData/Local/dumb_installer/lib/dumb_builds").expanduser()
PROJECT_NAME = "dumb_installer"
CONFIG_FILE = "dumb_build.toml"
SHABANG = "#!/usr/bin/env sh"
METADATA_FILE = ".dumb_install_metadata.json"
# Clones are scratch: gettempdir() rather than a hardcoded "/tmp", which on
# windows is a drive-relative path ("C:\tmp") that a non-admin user usually
# cannot create.
GIT_CLONE_DIR = Path(tempfile.gettempdir()) / "dumb_installer_clones"

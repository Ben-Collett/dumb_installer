from pathlib import Path
import shutil
import os
import stat
import sys

from platform_utils import is_windows


# shutil.rmtree gained onexc in 3.12; onerror is the 3.11 spelling and takes
# sys.exc_info() instead of the exception itself.
_RMTREE_ERROR_KWARG = "onexc" if sys.version_info >= (3, 12) else "onerror"


def _clear_readonly(path: str) -> None:
    """Drop the read-only bit so windows will let the file be deleted.

    Keeps the existing mode rather than setting a bare S_IWRITE, so a file
    that was executable stays executable.
    """
    try:
        mode = os.stat(path).st_mode
    except OSError:
        mode = 0

    os.chmod(path, mode | stat.S_IWRITE)


def _unlock_and_retry(func, path, exc):
    """rmtree error handler: make the entry writable, then retry the op."""
    try:
        _clear_readonly(path)
    except OSError:
        # Could not unlock it, so surface the original failure rather than a
        # confusing chmod error. onerror hands over sys.exc_info().
        raise exc[1] if isinstance(exc, tuple) else exc

    func(path)


def rmtree(path: Path) -> None:
    """shutil.rmtree that can also delete git's read-only pack files.

    git marks the pack files it writes into .git/objects/pack read-only.
    posix ignores mode bits when unlinking, so this never mattered there, but
    windows enforces the attribute and unlink fails with ERROR_ACCESS_DENIED
    (WinError 5). Any git install deletes such a tree, so without this every
    `din user/repo` install dies during cleanup.
    """
    shutil.rmtree(path, **{_RMTREE_ERROR_KWARG: _unlock_and_retry})


def copy_tree(src: Path, dest: Path, ignore=None, dirs_exist_ok: bool = False) -> None:
    """copytree with symlinks=True, falling back to copying link contents.

    Preserving symlinks needs SeCreateSymbolicLinkPrivilege on windows, so an
    unprivileged (or non-Developer-Mode) install of any project containing a
    symlink would fail outright. Where that happens the symlinks are
    dereferenced instead: the files still arrive, just duplicated rather than
    linked. On posix symlinks are recreated exactly as before.
    """
    try:
        shutil.copytree(src, dest, symlinks=True, ignore=ignore,
                        dirs_exist_ok=dirs_exist_ok)
        return
    except (OSError, NotImplementedError):
        if not is_windows():
            raise

    # removes partial write from the try catch on windows, usaly because of the symlinks requiring privileges
    if dest.exists():
        rmtree(dest)

    shutil.copytree(src, dest, symlinks=False, ignore=ignore)


def copy_project(src: Path, dest: Path, exclude) -> None:
    if dest.exists():
        rmtree(dest)

    copy_tree(src, dest, ignore=shutil.ignore_patterns(*exclude))


def files_differ(path1: Path, path2: Path, chunk_size: int = 8192) -> bool:
    """Compare two files efficiently with early exit."""

    # Fast check: size mismatch
    if path1.stat().st_size != path2.stat().st_size:
        return True

    # Compare contents in chunks
    with path1.open("rb") as f1, path2.open("rb") as f2:
        while True:
            b1 = f1.read(chunk_size)
            b2 = f2.read(chunk_size)
            if b1 != b2:
                return True
            if not b1:  # EOF
                return False


def directories_differ(dir1: Path, dir2: Path, ignore_patterns=None) -> bool:
    """
    Return True if directories differ, False if identical.
    Stops at first detected difference.
    """

    ignore = (
        shutil.ignore_patterns(*ignore_patterns)
        if ignore_patterns
        else None
    )

    def walk(base):
        for root, dirs, files in os.walk(base):
            root_path = Path(root)

            if ignore:
                ignored = ignore(str(root_path), dirs + files)
                dirs[:] = [d for d in dirs if d not in ignored]
                files = [f for f in files if f not in ignored]

            yield root_path, dirs, files

    # First pass: check dir1 against dir2
    for root1, dirs1, files1 in walk(dir1):
        rel_root = root1.relative_to(dir1)
        root2 = dir2 / rel_root

        # Directory missing
        if not root2.exists():
            return True

        # Compare files
        for name in files1:
            file1 = root1 / name
            file2 = root2 / name

            if not file2.exists():
                return True

            if files_differ(file1, file2):
                return True

        # Check for extra files in dir2 at this level
        names2 = set(
            f.name for f in root2.iterdir()
            if f.is_file()
        )
        if ignore:
            ignored = ignore(str(root2), list(names2))
            names2 -= set(ignored)

        if set(files1) != names2:
            return True

    # Second pass: detect extra directories/files in dir2
    for root2, _, _ in walk(dir2):
        rel_root = root2.relative_to(dir2)
        if not (dir1 / rel_root).exists():
            return True

    return False


def remove_excluded(root_path: Path, excluded: list[str]):
    """
    Removes files and directories under root_path that match
    any of the glob patterns in `excluded`.
    """
    # Create the ignore callable (same style as copytree)
    # determine_to_remove is a function which takes a path to a directory
    # and file name sand returns all the files in that list which need to be removed
    determine_to_remove = shutil.ignore_patterns(*excluded)

    # Walk bottom-up so directories can be removed safely
    for current_root, dirs, files in os.walk(root_path, topdown=False):
        current_root_path = Path(current_root)

        # Get names that should be removed
        names = dirs + files
        to_remove = determine_to_remove(current_root, names)

        for name in to_remove:
            path = current_root_path / name
            if path.is_dir():
                rmtree(path)
            elif path.exists():
                path.unlink()

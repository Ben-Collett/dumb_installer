from pathlib import Path
import shutil
import os


def copy_project(src: Path, dest: Path, exclude) -> None:
    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(
        src,
        dest,
        symlinks=True,
        ignore=shutil.ignore_patterns(*exclude),
    )


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
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

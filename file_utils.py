from pathlib import Path
import hashlib
import shutil
import os


# NOTE: file_hash and comparedirectoires are unused code I should delete them in a future version
def file_hash(path: Path, chunk_size: int = 8192) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def compare_directories(dir1: str, dir2: str, ignore_patterns=None):
    """
    Compare two directories recursively and return differences.

    Parameters:
        dir1, dir2: directories to compare
        ignore_patterns: list of glob-style patterns
                         (same behavior as shutil.copytree ignore)

    Returns:
        {
            "only_in_dir1": [...],
            "only_in_dir2": [...],
            "different_files": [...]
        }
    """

    dir1 = Path(dir1)
    dir2 = Path(dir2)

    ignore = (
        shutil.ignore_patterns(*ignore_patterns)
        if ignore_patterns
        else None
    )

    def collect_files(base: Path):
        files = {}

        for root, dirs, filenames in os_walk(base):
            root_path = Path(root)

            # Apply ignore function like copytree does
            if ignore:
                ignored = ignore(str(root_path), dirs + filenames)
                dirs[:] = [d for d in dirs if d not in ignored]
                filenames = [f for f in filenames if f not in ignored]

            for name in filenames:
                full_path = root_path / name
                rel_path = full_path.relative_to(base)
                files[rel_path] = full_path

        return files

    def os_walk(path):
        return os.walk(path)

    files1 = collect_files(dir1)
    files2 = collect_files(dir2)

    only_in_dir1 = sorted(set(files1) - set(files2))
    only_in_dir2 = sorted(set(files2) - set(files1))

    different_files = []
    for common in set(files1) & set(files2):
        if file_hash(files1[common]) != file_hash(files2[common]):
            different_files.append(common)

    return {
        "only_in_dir1": [str(p) for p in only_in_dir1],
        "only_in_dir2": [str(p) for p in only_in_dir2],
        "different_files": [str(p) for p in sorted(different_files)],
    }


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


def directories_differ(dir1: str, dir2: str, ignore_patterns=None) -> bool:
    """
    Return True if directories differ, False if identical.
    Stops at first detected difference.
    """

    dir1 = Path(dir1)
    dir2 = Path(dir2)

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

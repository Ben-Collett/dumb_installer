import sys
from typing import Optional


def print_debug(*values, sep: Optional[str], end: Optional[str], file: Optional[str], flush: bool = False):
    print(*values, sep=sep, end=end, file=file, flush=flush)


def error(msg: str) -> None:
    print(f"dumb_builder error: {msg}", file=sys.stderr)
    sys.exit(1)

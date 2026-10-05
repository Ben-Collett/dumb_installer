"""Smoke tests: the harness itself works, and `din` starts."""

import subprocess
import sys

import pytest

from conftest import requires_bwrap

pytestmark = [requires_bwrap, pytest.mark.sandbox]


def test_help_exits_zero(sandbox):
    result = sandbox.run(["--help"])
    assert result.returncode == 0


def test_sandbox_paths_are_writable(sandbox):
    """The sandbox really does provide writable absolute system paths."""
    probe = subprocess.run(
        sandbox.argv(
            [
                sys.executable,
                "-c",
                "from pathlib import Path;"
                "Path('/usr/local/bin/.probe').write_text('x');"
                "Path('/usr/lib/dumb_builds/.probe').mkdir(exist_ok=True);"
                "print('ok')",
            ]
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert probe.returncode == 0, probe.stderr
    assert (sandbox.bin_dir / ".probe").is_file()
    assert (sandbox.lib_dir / ".probe").is_dir()


def test_writes_do_not_escape_to_the_host(sandbox):
    """Anything the installer writes lands in the host tmpdir we control."""
    result = sandbox.run(["--init", "probe", "true"], cwd=sandbox.root)
    assert result.returncode == 0
    # `--init` writes dumb_build.toml into the cwd it was given.
    assert not (sandbox.bin_dir / "dumb_build.toml").exists()

"""Shared fixtures for the dumb_installer test suite.

Design notes (see TESTING_PLAN.md):

* Tests assert on observable behaviour -- exit codes, filesystem state, generated
  wrapper contents -- never on exact message wording.
* Filesystem and git behaviour is exercised for real (real tmpdirs, real git
  binary over ``file://``), not mocked.
* Anything touching ``/usr/local/bin``, ``/usr/lib`` or ``/etc`` runs inside a
  bubblewrap sandbox. ``bwrap`` cannot mount inside a read-only bind, so ``/etc``
  is a tmpfs with the essential files re-bound in.
* ``is_root()`` keys off ``$SUDO_UID`` rather than the real uid, so system-wide
  and per-user installs are both reachable by setting the env var.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "dumb_installer.py"

# The report never asserts exact message text; these are the only stream
# expectations, and only for argparse's own usage errors.
USAGE_EXIT = 2

requires_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None,
    reason="bwrap not found; sandboxed tests skipped (see TESTING_PLAN.md section 3.2)",
)


# --------------------------------------------------------------------------
# Sandbox
# --------------------------------------------------------------------------


@dataclass
class Sandbox:
    """A bwrap sandbox whose 'system' paths are backed by host temp dirs.

    Because the bind targets are host directories, a test can inspect the real
    artifacts the installer produced after the subprocess exits.
    """

    root: Path
    bin_dir: Path
    lib_parent: Path
    lib_dir: Path
    etc_dir: Path
    tmp_dir: Path
    config_home: Path
    user_bin: Path = None
    user_lib: Path = None

    # Inside the sandbox the installer lives here, and tests chdir to the
    # project via this. Both are binds of host paths, so the installer and the
    # project under test are genuinely visible.
    REPO_MOUNT = "/repo"
    WORK_MOUNT = "/work"
    USER_BIN_MOUNT = "/user_bin"
    USER_LIB_MOUNT = "/user_lib"

    def argv(self, cmd, env=None, cwd=None, workdir=None) -> list[str]:
        """Build the bwrap command line for ``cmd``."""
        passthrough = []
        for key, value in (env or {}).items():
            passthrough += ["--setenv", key, str(value)]

        binds = []
        if workdir is not None:
            binds += ["--bind", str(workdir), self.WORK_MOUNT]

        return [
            "bwrap",
            # /usr is bound read-only and wholesale; /bin, /lib, /sbin and
            # /lib64 are left as the host's own symlinks (on merged-/usr
            # systems they point into /usr, which resolves correctly). Only
            # /usr/lib is overlaid, because uninstall needs to remove the
            # install dir itself when it becomes empty.
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/sbin", "/sbin",
            # bwrap cannot create a mount point inside a read-only bind, so
            # /etc is a tmpfs and the files we need are re-bound individually.
            "--tmpfs", "/etc",
            "--ro-bind", "/etc/passwd", "/etc/passwd",
            "--ro-bind", "/etc/group", "/etc/group",
            "--ro-bind", "/etc/shadow", "/etc/shadow",
            "--ro-bind", "/etc/ssl", "/etc/ssl",
            "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
            "--ro-bind", "/etc/hosts", "/etc/hosts",
            "--bind", str(self.etc_dir), "/etc/dumb_installer",
            "--bind", str(self.bin_dir), "/usr/local/bin",
            # uninstall removes the install dir itself once it is empty, which
            # needs a writable /usr/lib. A plain tmpfs would hide libpython
            # and friends, and copying the real /usr/lib costs ~16G, so the
            # tmpfs is immediately overlaid with the real directory read-only
            # and only dumb_builds is made writable on top. Order matters.
            "--tmpfs", "/usr/lib",
            "--ro-bind", "/usr/lib", "/usr/lib",
            "--bind", str(self.lib_dir), "/usr/lib/dumb_builds",
            "--bind", str(self.config_home), "/xdg_config",
            # Per-user install targets, used when a config.toml pins them.
            "--bind", str(self.user_bin), self.USER_BIN_MOUNT,
            "--bind", str(self.user_lib), self.USER_LIB_MOUNT,
            "--ro-bind", str(REPO_ROOT), self.REPO_MOUNT,
            "--tmpfs", str(self.tmp_dir),
            "--proc", "/proc",
            "--dev", "/dev",
            "--unshare-all",
            "--die-with-parent",
            *binds,
            "--chdir", str(cwd) if cwd else "/",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "HOME", "/etc",
            "--setenv", "XDG_CONFIG_HOME", "/xdg_config",
        ] + passthrough + [str(c) for c in cmd]

    def run(self, args, env=None, cwd=None, workdir=None, stdin=None, as_root=True):
        """Run the installer (or any argv) inside the sandbox.

        ``cwd`` is a host path; it is made visible in the sandbox (bound to
        /work by default) and becomes the working directory.

        ``as_root`` controls ``SUDO_UID``, which is what ``is_root()`` reads --
        it does not grant any real privilege.
        """
        if workdir is None:
            workdir = cwd
        full_env = dict(env or {})
        if as_root:
            full_env["SUDO_UID"] = "1000"
        else:
            full_env.pop("SUDO_UID", None)

        # Translate a host path into its location inside the sandbox. A cwd
        # under the bound workdir lands at the equivalent spot under /work.
        if cwd is None:
            inner_cwd = self.REPO_MOUNT
        elif workdir is not None and Path(cwd).is_relative_to(Path(workdir)):
            inner_cwd = str(self.WORK_MOUNT / Path(cwd).relative_to(workdir))
        else:
            inner_cwd = str(cwd)

        cmd = [
            sys.executable,
            f"{self.REPO_MOUNT}/dumb_installer.py",
            *[str(a) for a in args],
        ]
        return subprocess.run(
            self.argv(cmd, env=full_env, cwd=inner_cwd, workdir=workdir),
            capture_output=True,
            text=True,
            input=stdin,
            timeout=120,
        )

    def write_global_config(self, on_install_auth=None, on_update_auth=None, **extra) -> Path:
        """Write the system-wide (/etc/dumb_installer) config.

        Note the auth keys are top-level, not under [paths] -- that is where
        Config reads them from.
        """
        # TOML: top-level keys must come *before* the [paths] table header,
        # or they are parsed as members of it.
        lines = []
        for key, value in {"on_install_auth": on_install_auth,
                           "on_update_auth": on_update_auth, **extra}.items():
            if value is not None:
                lines.append(f'{key} = "{value}"')
        lines += [
            "[paths]",
            'bin_dir = "/usr/local/bin"',
            'project_install_dir = "/usr/lib/dumb_builds"',
        ]
        path = self.etc_dir / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        return path

    # -- convenience accessors -------------------------------------------

    def wrapper_path(self, name: str) -> Path:
        return self.bin_dir / name

    def project_path(self, name: str) -> Path:
        return self.lib_dir / name

    def user_config_path(self) -> Path:
        """Where a per-user run keeps its config (XDG_CONFIG_HOME)."""
        return self.config_home / "dumb_installer" / "config.toml"

    def write_user_config(self, bin_dir=None, install_dir=None, **extra) -> Path:
        """Create a per-user config.toml pinning the install paths.

        The paths are sandbox mount points, not host paths, so the installer
        sees them exactly where the test expects them to be. Both privilege
        modes are driven through this so the test exercises real config
        parsing rather than relying on the import-time ``~`` expansion.
        """
        lines = ["[paths]"]
        lines.append(f'bin_dir = "{bin_dir or self.USER_BIN_MOUNT}"')
        lines.append(f'project_install_dir = "{install_dir or self.USER_LIB_MOUNT}"')
        for key, value in extra.items():
            lines.append(f'{key} = "{value}"')
        path = self.user_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        return path


@pytest.fixture
def sandbox(tmp_path_factory):
    """A fresh bwrap sandbox per test, so tests cannot leak into each other."""
    if shutil.which("bwrap") is None:
        pytest.skip("bwrap not found")

    root = tmp_path_factory.mktemp("sandbox")
    lib_parent = root / "usr_lib"
    box = Sandbox(
        root=root,
        bin_dir=root / "usr_local_bin",
        lib_parent=lib_parent,
        lib_dir=lib_parent / "dumb_builds",
        etc_dir=root / "etc_dumb_installer",
        tmp_dir=root / "tmp",
        config_home=root / "xdg_config",
    )
    box.user_bin = root / "user_bin"
    box.user_lib = root / "user_lib"
    for d in (
        box.bin_dir,
        box.lib_parent,
        box.lib_dir,
        box.etc_dir,
        box.tmp_dir,
        box.config_home,
        box.user_bin,
        box.user_lib,
    ):
        d.mkdir(parents=True, exist_ok=True)
    return box


# --------------------------------------------------------------------------
# Project fixtures
# --------------------------------------------------------------------------

PY_MAIN = '''\
import sys
print("hello from", __file__)
sys.exit(0)
'''


def write_project(root: Path, name="mytool", command=None, extra_files=None, **build) -> Path:
    """Create a minimal installable project under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.py").write_text(PY_MAIN)
    (root / "notes.txt").write_text("some data\n")
    (root / "__pycache__").mkdir(exist_ok=True)
    (root / "__pycache__" / "junk.pyc").write_text("nope")
    (root / ".git").mkdir(exist_ok=True)
    (root / ".git" / "config").write_text("[core]\n")

    for rel, content in (extra_files or {}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    build.setdefault("executable_name", name)
    build.setdefault("command", command or "python $dumb_project_dir/main.py")
    build.setdefault("excluded", ["__pycache__", "*.pyc", ".git"])

    lines = ["[build]"]
    for key, value in build.items():
        if key == "excluded":
            lines.append("excluded = [" + ", ".join(f'"{e}"' for e in value) + "]")
        elif isinstance(value, list):
            lines.append(f"{key} = [" + ", ".join(f'"{e}"' for e in value) + "]")
        elif value is None:
            continue
        else:
            lines.append(f'{key} = "{value}"')
    (root / "dumb_build.toml").write_text("\n".join(lines) + "\n")
    return root


@pytest.fixture
def project(tmp_path):
    """A valid, installable project directory."""
    return write_project(tmp_path / "proj")


# --------------------------------------------------------------------------
# Real git repositories over file://
# --------------------------------------------------------------------------


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path_factory):
    """A real bare repo on file:// with one commit, plus a helper to add more.

    Exercises the genuine git binary -- real shallow clone, stash, fetch,
    ``reset --hard`` and ``gc`` -- with no network involved.
    """
    if shutil.which("git") is None:
        pytest.skip("git not found")

    base = tmp_path_factory.mktemp("gitrepo")
    work = base / "work"
    work.mkdir()
    _git("init", "-b", "main", cwd=work)
    _git("config", "user.email", "test@example.com", cwd=work)
    _git("config", "user.name", "Test", cwd=work)
    _git("config", "commit.gpgsign", "false", cwd=work)

    # A project installed from git must keep its .git directory, or --update
    # has no repository to fetch into. Only the local install drops it.
    write_project(
        work,
        name="gittool",
        excluded=["__pycache__", "*.pyc"],
        local_install_excluded=[".git"],
    )

    bare = base / "origin.git"
    _git("init", "--bare", "-b", "main", str(bare), cwd=base)
    _git("remote", "add", "origin", str(bare), cwd=work)
    _git("add", "-A", cwd=work)
    _git("commit", "-m", "initial", cwd=work)
    _git("push", "-u", "origin", "main", cwd=work)

    def add_commit(message: str, files: dict | None = None):
        for rel, content in (files or {}).items():
            target = work / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        _git("add", "-A", cwd=work)
        _git("commit", "-m", message, cwd=work)
        _git("push", "origin", "main", cwd=work)
        return _git("rev-parse", "HEAD", cwd=work).stdout.strip()

    return {"url": f"file://{bare}", "work": work, "bare": bare, "add_commit": add_commit}


@pytest.fixture
def user_env():
    """Env for a non-sudo (per-user) invocation."""
    return {}

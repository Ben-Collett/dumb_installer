"""Phase 6: git install and update, against real repositories over file://.

The genuine git binary is exercised -- real shallow clones, real stash,
fetch, rev-parse, reset --hard and gc. Nothing is mocked.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import requires_bwrap
from git_wrapper import GitWrapper
from meta_data import MetaData

pytestmark = pytest.mark.sandbox


def git(*args, cwd, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


# ===========================================================================
# GitWrapper unit behaviour, in-process against real repos
# ===========================================================================


def test_is_git_installed_true():
    assert GitWrapper().is_git_installed() is True


def test_clone_to_succeeds(git_repo, tmp_path):
    dest = tmp_path / "clone"
    result = GitWrapper().cloneTo(git_repo["url"], str(dest))
    assert result.success is True
    assert (dest / "dumb_build.toml").is_file()


def test_clone_is_shallow_without_a_commit(git_repo, tmp_path):
    dest = tmp_path / "clone"
    GitWrapper().cloneTo(git_repo["url"], str(dest))
    # A --depth 1 clone has a single commit.
    log = git("rev-list", "--count", "HEAD", cwd=dest)
    assert log.stdout.strip() == "1"


def test_clone_at_a_specific_commit(git_repo, tmp_path):
    first = git("rev-parse", "HEAD", cwd=git_repo["work"]).stdout.strip()
    git_repo["add_commit"]("second", {"newfile.txt": "second\n"})
    second = git("rev-parse", "HEAD", cwd=git_repo["work"]).stdout.strip()

    dest = tmp_path / "clone"
    result = GitWrapper().cloneTo(git_repo["url"], str(dest), commit=first)
    assert result.success is True
    head = git("rev-parse", "HEAD", cwd=dest).stdout.strip()
    assert head == first
    assert not (dest / "newfile.txt").exists()

    other = tmp_path / "clone2"
    assert GitWrapper().cloneTo(git_repo["url"], str(other), commit=second).success
    assert (other / "newfile.txt").is_file()


def test_clone_unknown_commit_fails(git_repo, tmp_path):
    dest = tmp_path / "clone"
    result = GitWrapper().cloneTo(git_repo["url"], str(dest), commit="deadbeef" * 5)
    assert result.success is False


def test_clone_refuses_non_empty_destination(git_repo, tmp_path):
    dest = tmp_path / "clone"
    dest.mkdir()
    (dest / "existing.txt").write_text("x")
    result = GitWrapper().cloneTo(git_repo["url"], str(dest))
    assert result.success is False


def test_clone_missing_repo_fails(tmp_path):
    result = GitWrapper().cloneTo("file:///nonexistent/repo.git", str(tmp_path / "c"))
    assert result.success is False


def test_url_resolution():
    wrapper = GitWrapper()
    for url in ["http://x/y", "https://x/y", "git://x/y", "ssh://x/y"]:
        assert wrapper._resolve_url(url) == url
    assert wrapper._resolve_url("user/repo") == "https://github.com/user/repo"


def test_custom_default_domain():
    wrapper = GitWrapper(default_domain="gitlab.com")
    assert wrapper._resolve_url("user/repo") == "https://gitlab.com/user/repo"


def test_check_can_do_git_on_a_real_repo(git_repo, tmp_path):
    dest = tmp_path / "clone"
    GitWrapper().cloneTo(git_repo["url"], str(dest))
    # Returns None (rather than a failure) when everything is in order.
    assert GitWrapper().check_can_do_git(dest) is None


def test_check_can_do_git_on_a_non_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = GitWrapper().check_can_do_git(plain)
    assert result is not None
    assert result.success is False


def test_check_can_do_git_on_a_missing_path(tmp_path):
    result = GitWrapper().check_can_do_git(tmp_path / "nope")
    assert result is not None
    assert result.success is False


# ===========================================================================
# updateRepoAtPath
# ===========================================================================


def test_update_pulls_a_new_commit(git_repo, tmp_path):
    dest = tmp_path / "clone"
    assert GitWrapper().cloneTo(git_repo["url"], str(dest)).success

    git_repo["add_commit"]("second", {"newfile.txt": "new\n"})

    result = GitWrapper().updateRepoAtPath(dest)
    assert result.success is True
    assert (dest / "newfile.txt").read_text() == "new\n"


def test_update_reports_already_up_to_date(git_repo, tmp_path):
    dest = tmp_path / "clone"
    GitWrapper().cloneTo(git_repo["url"], str(dest))
    result = GitWrapper().updateRepoAtPath(dest)
    assert result.success is False
    assert "up to date" in result.failureMessage


def test_update_discards_local_modifications(git_repo, tmp_path):
    dest = tmp_path / "clone"
    GitWrapper().cloneTo(git_repo["url"], str(dest))
    git_repo["add_commit"]("second", {"newfile.txt": "new\n"})

    (dest / "main.py").write_text("locally modified\n")
    (dest / "untracked.txt").write_text("junk\n")

    assert GitWrapper().updateRepoAtPath(dest).success is True
    assert (dest / "untracked.txt").exists() is False


def test_update_on_a_non_repo_fails(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = GitWrapper().updateRepoAtPath(plain)
    assert result.success is False


# ===========================================================================
# Stash round-trip
# ===========================================================================


def test_full_stash_then_pop_restores_changes(git_repo, tmp_path):
    dest = tmp_path / "clone"
    GitWrapper().cloneTo(git_repo["url"], str(dest))
    (dest / "main.py").write_text("dirty\n")

    GitWrapper().full_stash(dest)
    assert (dest / "main.py").read_text() != "dirty\n"

    GitWrapper().pop_stash(dest)
    assert (dest / "main.py").read_text() == "dirty\n"


def test_full_stash_includes_untracked_files(git_repo, tmp_path):
    dest = tmp_path / "clone"
    GitWrapper().cloneTo(git_repo["url"], str(dest))
    (dest / "untracked.txt").write_text("new\n")

    GitWrapper().full_stash(dest)
    assert not (dest / "untracked.txt").exists()

    GitWrapper().pop_stash(dest)
    assert (dest / "untracked.txt").read_text() == "new\n"


def test_clear_stash_affects_only_the_named_repo(git_repo, tmp_path):
    """Regression: clear_stash used to run with no cwd, so it cleared whichever
    repository happened to be the process's working directory."""
    one = tmp_path / "one"
    two = tmp_path / "two"
    for dest in (one, two):
        assert GitWrapper().cloneTo(git_repo["url"], str(dest)).success
        (dest / "main.py").write_text("dirty\n")
        GitWrapper().full_stash(dest)

    # Both start with a stash.
    assert git("stash", "list", cwd=one).stdout.strip()
    assert git("stash", "list", cwd=two).stdout.strip()

    GitWrapper().clear_stash(one)

    # `one` is emptied, `two` is untouched.
    assert git("stash", "list", cwd=one).stdout.strip() == ""
    assert git("stash", "list", cwd=two).stdout.strip() != ""


# ===========================================================================
# Error mapping
# ===========================================================================


def test_error_mapping_for_missing_repo(tmp_path):
    result = GitWrapper().cloneTo("file:///no/such/repo.git", str(tmp_path / "c"))
    assert result.success is False
    assert result.failureMessage


def test_error_mapping_for_non_repo_directory(tmp_path):
    result = GitWrapper().updateRepoAtPath(tmp_path)
    assert result.success is False


# ===========================================================================
# End-to-end git install and update, in the sandbox
# ===========================================================================


def _sandboxed_repo(sandbox, git_repo):
    """Bind the repo tree into the sandbox and return a usable file:// url.

    The bare repo lives on the host, so the sandbox only sees it once its
    parent directory is bound as the workdir. The url therefore has to be
    rewritten to the in-sandbox path.
    """
    workdir = git_repo["bare"].parent
    url = f"file://{sandbox.WORK_MOUNT}/{git_repo['bare'].name}"
    return workdir, url


def _sandboxed_repo(sandbox, git_repo):
    """Bind the repo tree into the sandbox and return a usable file:// url.

    The bare repo lives on the host, so the sandbox only sees it once its
    parent directory is bound as the workdir. The url therefore has to be
    rewritten to the in-sandbox path.

    Note that git records whatever url it was cloned from in the installed
    repo's ``origin`` remote, so the rewritten url is the one later fetches
    must use too -- which is what these tests drive.
    """
    workdir = git_repo["bare"].parent
    url = f"file://{sandbox.WORK_MOUNT}/{git_repo['bare'].name}"
    return workdir, url


def test_git_install_from_url(sandbox, git_repo):
    workdir, url = _sandboxed_repo(sandbox, git_repo)
    result = sandbox.run([url], cwd=workdir, workdir=workdir)
    assert result.returncode == 0, result.stdout + result.stderr

    assert (sandbox.project_path("gittool") / "dumb_build.toml").is_file()
    assert sandbox.wrapper_path("gittool").is_file()
    meta = json.loads(
        (sandbox.project_path("gittool") / ".dumb_install_metadata.json").read_text()
    )
    assert meta["is_git_install"] is True


def test_git_install_leaves_no_temp_clone(sandbox, git_repo):
    import subprocess
    import sys

    workdir, url = _sandboxed_repo(sandbox, git_repo)
    assert sandbox.run([url], cwd=workdir, workdir=workdir).returncode == 0

    listing = subprocess.run(
        sandbox.argv(
            [sys.executable, "-c",
             "from pathlib import Path;"
             "print([p.name for p in Path('/tmp').iterdir()])"]
        ),
        capture_output=True, text=True, timeout=60,
    )
    assert "temp_clone" not in listing.stdout


def test_git_install_of_missing_repo_fails(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = sandbox.run(["file:///no/such/repo.git"], cwd=work, workdir=work)
    assert result.returncode != 0
    assert not list(sandbox.bin_dir.iterdir()), "a failed install must not leave a wrapper"


def test_git_install_at_specific_commit(sandbox, git_repo):
    workdir, url = _sandboxed_repo(sandbox, git_repo)
    first = git("rev-parse", "HEAD", cwd=git_repo["work"]).stdout.strip()
    git_repo["add_commit"]("second", {"later.txt": "later\n"})

    result = sandbox.run([url, first], cwd=workdir, workdir=workdir)
    assert result.returncode == 0, result.stdout + result.stderr
    installed = sandbox.project_path("gittool")
    assert (installed / "dumb_build.toml").is_file()
    assert not (installed / "later.txt").exists(), "should be the older commit"


def test_git_install_at_bad_commit_fails(sandbox, git_repo):
    workdir, url = _sandboxed_repo(sandbox, git_repo)
    result = sandbox.run([url, "0" * 40], cwd=workdir, workdir=workdir)
    assert result.returncode != 0
    assert not list(sandbox.bin_dir.iterdir())


# The update tests below need the installed repo's `origin` remote to resolve
# inside the sandbox, so they repoint it at the sandbox-visible path first.
# In real use the remote is whatever the user cloned from, which is reachable.


def _repoint_remote(sandbox, git_repo, name="gittool"):
    import subprocess
    import sys

    installed = sandbox.project_path(name)
    git("remote", "set-url", "origin",
        f"file://{sandbox.WORK_MOUNT}/{git_repo['bare'].name}", cwd=installed)


def test_git_update_pulls_new_commit(sandbox, git_repo):
    workdir, url = _sandboxed_repo(sandbox, git_repo)
    assert sandbox.run([url], cwd=workdir, workdir=workdir).returncode == 0
    _repoint_remote(sandbox, git_repo)

    git_repo["add_commit"]("second", {"fresh.txt": "fresh\n"})

    result = sandbox.run(["--update", "gittool"], workdir=workdir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (sandbox.project_path("gittool") / "fresh.txt").read_text() == "fresh\n"


def test_git_update_reports_up_to_date(sandbox, git_repo):
    workdir, url = _sandboxed_repo(sandbox, git_repo)
    assert sandbox.run([url], cwd=workdir, workdir=workdir).returncode == 0
    _repoint_remote(sandbox, git_repo)

    result = sandbox.run(["--update", "gittool"], workdir=workdir)
    assert result.returncode == 0
    assert (sandbox.project_path("gittool") / "main.py").is_file()

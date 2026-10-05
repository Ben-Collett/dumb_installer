"""Update and update-all, against the sandbox and real git repos."""

import json

import pytest

from conftest import requires_bwrap, write_project


def read_metadata(installed):
    return json.loads((installed / ".dumb_install_metadata.json").read_text())


# ===========================================================================
# Local (non-git) updates
# ===========================================================================


@requires_bwrap
def test_update_detects_a_changed_file(sandbox, tmp_path):
    proj = write_project(tmp_path / "proj", name="mytool")
    assert sandbox.run([], cwd=proj).returncode == 0

    installed = sandbox.project_path("mytool")
    (proj / "main.py").write_text("print('updated content')\n")

    result = sandbox.run(["--update", "mytool"], cwd=proj)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (installed / "main.py").read_text() == "print('updated content')\n"


@requires_bwrap
def test_update_picks_up_a_new_file(sandbox, tmp_path):
    proj = write_project(tmp_path / "proj", name="mytool")
    assert sandbox.run([], cwd=proj).returncode == 0

    (proj / "brand_new.py").write_text("x = 1\n")
    result = sandbox.run(["--update", "mytool"], cwd=proj)
    assert result.returncode == 0
    assert (sandbox.project_path("mytool") / "brand_new.py").is_file()


@requires_bwrap
def test_update_reports_already_up_to_date(sandbox, tmp_path):
    proj = write_project(tmp_path / "proj", name="mytool")
    assert sandbox.run([], cwd=proj).returncode == 0

    result = sandbox.run(["--update", "mytool"], cwd=proj)
    assert result.returncode == 0
    assert "up to date" in (result.stdout + result.stderr).lower()


@requires_bwrap
def test_update_ignores_excluded_files(sandbox, tmp_path):
    """A change to an excluded file must not count as an update."""
    proj = write_project(tmp_path / "proj", name="mytool")
    assert sandbox.run([], cwd=proj).returncode == 0

    (proj / "scratch.pyc").write_text("noise\n")
    (proj / "__pycache__").mkdir(exist_ok=True)
    (proj / "__pycache__" / "junk.pyc").write_text("noise\n")

    result = sandbox.run(["--update", "mytool"], cwd=proj)
    assert result.returncode == 0
    assert "up to date" in (result.stdout + result.stderr).lower()


@requires_bwrap
def test_update_of_unknown_program_fails(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = sandbox.run(["--update", "not-installed"], cwd=work)
    assert result.returncode != 0


@requires_bwrap
def test_update_without_metadata_fails(sandbox, tmp_path):
    """A directory in the install path that is not a managed install."""
    work = tmp_path / "work"
    work.mkdir()
    rogue = sandbox.lib_dir / "rogue"
    rogue.mkdir(parents=True, exist_ok=True)
    result = sandbox.run(["--update", "rogue"], cwd=work)
    assert result.returncode != 0


@requires_bwrap
def test_update_all_visits_every_install(sandbox, tmp_path):
    # Both projects must be installed under one shared workdir, otherwise each
    # records source_path=/work and they collide.
    first = write_project(tmp_path / "a", name="first")
    second = write_project(tmp_path / "b", name="second")
    assert sandbox.run([], cwd=first, workdir=tmp_path).returncode == 0
    assert sandbox.run([], cwd=second, workdir=tmp_path).returncode == 0

    assert read_metadata(sandbox.project_path("first"))["source_path"] != \
        read_metadata(sandbox.project_path("second"))["source_path"]

    (first / "main.py").write_text("print('one')\n")
    (second / "main.py").write_text("print('two')\n")

    result = sandbox.run(["--update-all"], cwd=tmp_path, workdir=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (sandbox.project_path("first") / "main.py").read_text() == "print('one')\n"
    assert (sandbox.project_path("second") / "main.py").read_text() == "print('two')\n"


@requires_bwrap
def test_update_all_with_nothing_installed(sandbox, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = sandbox.run(["--update-all"], cwd=work)
    assert result.returncode == 0


@requires_bwrap
def test_failing_hook_reverts_the_update(sandbox, tmp_path):
    """A non-zero on_update must leave the previous version in place."""
    sandbox.write_global_config(on_update_auth="auto approve")
    proj = write_project(tmp_path / "proj", name="mytool")
    assert sandbox.run([], cwd=proj).returncode == 0
    installed = sandbox.project_path("mytool")

    (proj / "dumb_build.toml").write_text(
        '[build]\n'
        'executable_name = "mytool"\n'
        'command = "python $dumb_project_dir/main.py"\n'
        'excluded = ["__pycache__", "*.pyc", ".git"]\n'
        'on_update = "exit 1"\n'
    )
    (proj / "main.py").write_text("print('would break')\n")

    result = sandbox.run(["--update", "mytool"], cwd=proj)
    assert result.returncode != 0, "a failed update must report failure"

    # The snapshot revert must have restored the pre-update content.
    assert (installed / "main.py").read_text() != "print('would break')\n"


@requires_bwrap
def test_metadata_records_a_local_install(sandbox, tmp_path):
    proj = write_project(tmp_path / "proj", name="mytool")
    assert sandbox.run([], cwd=proj).returncode == 0
    data = read_metadata(sandbox.project_path("mytool"))
    assert data["is_git_install"] is False
    assert data["source_path"]


@requires_bwrap
def test_metadata_is_a_bool_not_a_url_or_null(sandbox, tmp_path):
    """Regression: is_git_install used to be args.url, so a local install
    serialised it as null."""
    proj = write_project(tmp_path / "proj", name="mytool")
    assert sandbox.run([], cwd=proj).returncode == 0
    raw = (sandbox.project_path("mytool") / ".dumb_install_metadata.json").read_text()
    assert "null" not in raw, "is_git_install must serialise as a bool"
    assert json.loads(raw)["is_git_install"] is False

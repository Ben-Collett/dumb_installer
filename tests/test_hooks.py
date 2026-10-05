"""Phase 5: on_install / on_update hooks and the auth modes.

Prompts are driven with real stdin (see TESTING_PLAN.md section 3.4) rather
than monkeypatched, so the whole path -- argparse, tty-less input(), and mode
resolution -- is genuinely exercised.
"""

import json
import shutil
from pathlib import Path

import pytest

from auth import AuthModes
from config import Config
from conftest import requires_bwrap, write_project
from dumb_installer import (
    authenticate_can_run_hook,
    authenticate_can_run_on_install,
    authenticate_can_run_on_update,
    safe_run_on_install_hook,
    safe_run_on_update_hook,
)
from build_config_utils import BuildConfig

# Only the end-to-end half needs the sandbox; the unit half runs anywhere.


class ScriptedPrompt:
    """Records what it was asked and replays canned answers."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def yes_or_no_prompt(self, msg):
        self.asked.append(msg)
        return self.answers.pop(0)


# run_in_dir goes through os.system, so a shell has to be on PATH.
requires_shell = pytest.mark.skipif(
    shutil.which("sh") is None, reason="no sh on PATH; hook execution cannot be tested"
)


def touch(name):
    """A hook command that creates a file using only a shell builtin.

    Using `touch` would make these tests depend on coreutils being on PATH;
    the shell's own redirection needs nothing but sh itself.
    """
    return f": > {name}"


def make_config(tmp_path, on_install=None, on_update=None):
    cfg = Config.__new__(Config)
    cfg.binary_dir = tmp_path / "bin"
    cfg.project_install_dir = tmp_path / "lib"
    cfg.on_install_mode = AuthModes.from_str(on_install)
    cfg.on_update_mode = AuthModes.from_str(on_update)
    return cfg


# ===========================================================================
# Mode resolution
# ===========================================================================


def test_auto_approve_skips_the_prompt(tmp_path):
    prompt = ScriptedPrompt()  # no answers: a prompt would raise IndexError
    assert authenticate_can_run_hook(
        AuthModes.AUTO_APPROVE, "on_install", "tool", prompt
    ) is True
    assert prompt.asked == []


def test_auto_reject_skips_the_prompt(tmp_path):
    prompt = ScriptedPrompt()
    assert authenticate_can_run_hook(
        AuthModes.AUTO_REJECT, "on_install", "tool", prompt
    ) is False
    assert prompt.asked == []


def test_manual_asks_the_prompt(tmp_path):
    prompt = ScriptedPrompt(True)
    assert authenticate_can_run_hook(
        AuthModes.MANUAL, "on_install", "tool", prompt
    ) is True
    assert len(prompt.asked) == 1
    assert "tool" in prompt.asked[0]


def test_manual_rejection(tmp_path):
    prompt = ScriptedPrompt(False)
    assert authenticate_can_run_hook(
        AuthModes.MANUAL, "on_update", "tool", prompt
    ) is False


def test_prompt_default_is_constructed_lazily():
    """Regression: the parameter used to default to a UserPrompt() instance
    evaluated once, at import time."""
    import inspect

    params = inspect.signature(authenticate_can_run_hook).parameters
    assert params["user_prompt"].default is None


# ===========================================================================
# safe_run_on_install_hook  (regression: guarded on on_update)
# ===========================================================================


@requires_shell
def test_install_hook_runs_when_only_on_install_is_set(tmp_path):
    """The bug: this returned HookSuccess without running anything, because it
    checked on_update instead of on_install."""
    build = write_project(tmp_path, on_install=touch("ran_install"))
    build_config = BuildConfig(build)
    assert build_config.on_update is None

    cfg = make_config(tmp_path, on_install="auto approve")
    from process_wrapper import ProcessWrapper

    result = safe_run_on_install_hook(cfg, build_config, ProcessWrapper(build))

    assert result.success() is True
    assert (build / "ran_install").exists(), "on_install hook should have run"


@requires_shell
def test_update_hook_runs_when_only_on_update_is_set(tmp_path):
    build = write_project(tmp_path, on_update=touch("ran_update"))
    build_config = BuildConfig(build)
    assert build_config.on_install is None

    cfg = make_config(tmp_path, on_update="auto approve")
    from process_wrapper import ProcessWrapper

    result = safe_run_on_update_hook(cfg, build_config, ProcessWrapper(build))

    assert result.success() is True
    assert (build / "ran_update").exists()


@requires_shell
def test_install_hook_runs_in_the_install_dir(tmp_path):
    build = write_project(tmp_path, on_install=touch("here"))
    build_config = BuildConfig(build)
    cfg = make_config(tmp_path, on_install="auto approve")
    from process_wrapper import ProcessWrapper

    safe_run_on_install_hook(cfg, build_config, ProcessWrapper(build))
    assert (build / "here").exists(), "hook must run inside the project dir"


@requires_shell
def test_no_install_hook_is_a_success(tmp_path):
    build = write_project(tmp_path)
    build_config = BuildConfig(build)
    cfg = make_config(tmp_path, on_install="auto approve")
    from process_wrapper import ProcessWrapper

    assert safe_run_on_install_hook(cfg, build_config, ProcessWrapper(build)).success()


@requires_shell
def test_failing_install_hook_is_reported(tmp_path):
    build = write_project(tmp_path, on_install="exit 3")
    build_config = BuildConfig(build)
    cfg = make_config(tmp_path, on_install="auto approve")
    from process_wrapper import ProcessWrapper

    result = safe_run_on_install_hook(cfg, build_config, ProcessWrapper(build))
    assert result.success() is False


@requires_shell
def test_rejected_install_hook_is_reported(tmp_path):
    build = write_project(tmp_path, on_install=touch("nope"))
    build_config = BuildConfig(build)
    cfg = make_config(tmp_path, on_install="auto reject")
    from process_wrapper import ProcessWrapper

    result = safe_run_on_install_hook(cfg, build_config, ProcessWrapper(build))
    assert result.success() is False
    assert not (build / "nope").exists(), "a rejected hook must not run"


@requires_shell
def test_failing_update_hook_is_reported(tmp_path):
    build = write_project(tmp_path, on_update="exit 1")
    build_config = BuildConfig(build)
    cfg = make_config(tmp_path, on_update="auto approve")
    from process_wrapper import ProcessWrapper

    assert safe_run_on_update_hook(cfg, build_config, ProcessWrapper(build)).success() is False


# ===========================================================================
# run_in_dir honours dir_override  (regression)
# ===========================================================================


@requires_shell
def test_run_in_dir_uses_the_override_directory(tmp_path):
    from process_wrapper import ProcessWrapper

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "marker").write_text("x")

    ProcessWrapper(tmp_path).run_in_dir("ls", dir_override=elsewhere)
    assert (elsewhere / "marker").is_file()


@requires_shell
def test_run_in_dir_uses_its_own_dir_by_default(tmp_path):
    from process_wrapper import ProcessWrapper

    here = tmp_path / "here"
    here.mkdir()
    here.joinpath("mine").write_text("x")

    ProcessWrapper(here).run_in_dir("ls")
    assert (here / "mine").is_file()


def test_run_in_dir_without_any_dir_asserts(tmp_path):
    from process_wrapper import ProcessWrapper

    with pytest.raises(AssertionError):
        ProcessWrapper(None).run_in_dir("ls")


def test_run_subprocess_in_dir_uses_the_override(tmp_path):
    import os
    import sys

    from process_wrapper import ProcessWrapper

    sub = tmp_path / "sub"
    sub.mkdir()
    proc = ProcessWrapper(tmp_path).run_subprocess_in_dir(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        dir_override=sub,
    )
    assert os.path.samefile(proc.stdout.strip(), sub)


# ===========================================================================
# End-to-end hooks, with real stdin
# ===========================================================================


@requires_bwrap
def test_install_hook_runs_end_to_end(sandbox, tmp_path):
    proj = write_project(
        tmp_path / "proj", name="hooked", on_install=touch("build_ran")
    )
    sandbox.write_global_config(on_install_auth="auto approve")

    result = sandbox.run([], cwd=proj)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (sandbox.project_path("hooked") / "build_ran").exists()


@requires_bwrap
def test_rejected_install_hook_rolls_back(sandbox, tmp_path):
    proj = write_project(
        tmp_path / "proj", name="hooked", on_install=touch("build_ran")
    )
    sandbox.write_global_config(on_install_auth="auto reject")

    result = sandbox.run([], cwd=proj, stdin="y\n")
    assert result.returncode != 0
    assert not sandbox.wrapper_path("hooked").exists()
    assert not sandbox.project_path("hooked").exists(), (
        "a rejected hook must leave no partial install"
    )


@requires_bwrap
def test_failing_install_hook_rolls_back(sandbox, tmp_path):
    proj = write_project(
        tmp_path / "proj", name="hooked", on_install="exit 1"
    )
    sandbox.write_global_config(on_install_auth="auto approve")

    result = sandbox.run([], cwd=proj)
    assert result.returncode != 0
    assert not sandbox.wrapper_path("hooked").exists()
    assert not sandbox.project_path("hooked").exists()


@requires_bwrap
def test_manual_prompt_approved_via_stdin(sandbox, tmp_path):
    proj = write_project(
        tmp_path / "proj", name="prompted", on_install=touch("approved")
    )
    sandbox.write_global_config(on_install_auth="manual")

    result = sandbox.run([], cwd=proj, stdin="y\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (sandbox.project_path("prompted") / "approved").exists()


@requires_bwrap
def test_manual_prompt_rejected_via_stdin(sandbox, tmp_path):
    proj = write_project(
        tmp_path / "proj", name="prompted", on_install=touch("approved")
    )
    sandbox.write_global_config(on_install_auth="manual")

    result = sandbox.run([], cwd=proj, stdin="n\n")
    assert result.returncode != 0
    assert not sandbox.project_path("prompted").exists()


@pytest.mark.parametrize("answer", ["yes", "Y", "YES"])
@requires_bwrap
@requires_bwrap
def test_prompt_accepts_word_forms(sandbox, tmp_path, answer):
    proj = write_project(
        tmp_path / "proj", name="prompted", on_install=touch("ok")
    )
    sandbox.write_global_config(on_install_auth="manual")
    result = sandbox.run([], cwd=proj, stdin=f"{answer}\n")
    assert result.returncode == 0, result.stdout + result.stderr


@requires_bwrap
def test_prompt_repeats_on_garbage(sandbox, tmp_path):
    proj = write_project(
        tmp_path / "proj", name="prompted", on_install=touch("ok")
    )
    sandbox.write_global_config(on_install_auth="manual")
    result = sandbox.run([], cwd=proj, stdin="maybe\nwhat\ny\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (sandbox.project_path("prompted") / "ok").exists()


@requires_bwrap
def test_on_update_hook_runs_on_update(sandbox, tmp_path):
    proj = write_project(tmp_path / "proj", name="hooked", on_update=touch("updated"))
    sandbox.write_global_config(on_update_auth="auto approve")

    assert sandbox.run([], cwd=proj).returncode == 0
    installed = sandbox.project_path("hooked")
    assert not (installed / "updated").exists()

    # Change the source so an update is warranted.
    (proj / "main.py").write_text("print('changed')\n")
    result = sandbox.run(["--update", "hooked"], cwd=proj)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (installed / "updated").exists()

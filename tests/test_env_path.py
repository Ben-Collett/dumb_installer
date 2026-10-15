"""env_path behaviour.

The registry value only exists on windows, so the real store is swapped for
an in-memory one; what is asserted is the entry arithmetic, what gets written
and announced, and how the running process is kept in step. The off-windows
refusal of the real store is covered directly.
"""

import os
import sys
from pathlib import Path

import pytest

from env_path import (
    RegistryUserPathStore,
    add_entry,
    add_path,
    contains_entry,
    join_path_entries,
    remove_entry,
    remove_path,
    split_path_entries,
)


class FakeStore:
    """Stands in for the Path value under HKCU\\Environment."""

    def __init__(self, value: str = ""):
        self.value = value
        self.writes: list[str] = []
        self.broadcasts = 0

    def read(self) -> str:
        return self.value

    def write(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def broadcast(self) -> None:
        self.broadcasts += 1


@pytest.fixture(autouse=True)
def _restore_process_path(monkeypatch):
    """Both functions rewrite os.environ['PATH']; put it back afterwards."""
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))


# ---------------------------------------------------------------------------
# entry arithmetic
# ---------------------------------------------------------------------------


def test_split_round_trips_through_join():
    value = "C:\\a;;C:\\b"
    assert join_path_entries(split_path_entries(value)) == value


@pytest.mark.parametrize("value", [None, ""])
def test_splitting_nothing_gives_no_entries(value):
    assert split_path_entries(value) == []


def test_contains_is_blind_to_case_and_trailing_separator():
    assert contains_entry(["C:\\Tools\\"], "c:\\tools")
    assert not contains_entry(["C:\\Tools\\"], "c:\\other")


def test_add_entry_is_idempotent():
    entries = ["C:\\a"]
    assert add_entry(entries, "C:\\A") == ["C:\\a"]
    assert add_entry(entries, "C:\\b") == ["C:\\a", "C:\\b"]


def test_remove_entry_does_not_alter_the_original_list():
    entries = ["C:\\a", "C:\\b"]
    assert remove_entry(entries, "C:\\a") == ["C:\\b"]
    assert entries == ["C:\\a", "C:\\b"]


# ---------------------------------------------------------------------------
# add_path
# ---------------------------------------------------------------------------


def test_add_writes_the_entry_on_the_end():
    store = FakeStore("C:\\Windows")
    add_path(Path("C:\\tools"), _store=store)
    assert store.value == "C:\\Windows;C:\\tools"
    assert store.broadcasts == 1


def test_add_creates_a_value_that_was_not_there():
    store = FakeStore()
    add_path(Path("C:\\tools"), _store=store)
    assert store.value == "C:\\tools"


def test_add_leaves_entries_it_does_not_own_alone():
    store = FakeStore("C:\\Windows;;C:\\Program Files")
    add_path(Path("C:\\tools"), _store=store)
    assert store.value == "C:\\Windows;;C:\\Program Files;C:\\tools"


def test_add_writes_nothing_when_already_listed():
    store = FakeStore("C:\\Tools\\")
    add_path(Path("c:\\tools"), _store=store)
    assert store.writes == []
    assert store.broadcasts == 0


# ---------------------------------------------------------------------------
# remove_path
# ---------------------------------------------------------------------------


def test_remove_drops_every_matching_entry():
    store = FakeStore("C:\\a;C:\\TOOLS;c:\\tools\\")
    remove_path(Path("C:\\tools"), _store=store)
    assert store.value == "C:\\a"
    assert store.broadcasts == 1


def test_remove_writes_nothing_when_not_listed():
    store = FakeStore("C:\\a")
    remove_path(Path("C:\\tools"), _store=store)
    assert store.writes == []
    assert store.broadcasts == 0


def test_remove_does_not_invent_a_value_on_a_clean_user():
    store = FakeStore()
    remove_path(Path("C:\\tools"), _store=store)
    assert store.writes == []


# ---------------------------------------------------------------------------
# the running process
# ---------------------------------------------------------------------------


def test_add_makes_the_entry_usable_by_this_process(monkeypatch):
    # Drive letters are avoided here: os.pathsep is ':' off windows, so the
    # process PATH is split with the separator of the platform under test.
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/opt/other"]))
    add_path(Path("/opt/tools"), _store=FakeStore())
    assert os.environ["PATH"].split(os.pathsep) == [
        "/usr/bin",
        "/opt/other",
        "/opt/tools",
    ]


def test_add_updates_the_process_even_when_the_registry_has_it(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    store = FakeStore("/opt/tools")
    add_path(Path("/opt/tools"), _store=store)
    assert store.writes == []
    assert "/opt/tools" in os.environ["PATH"].split(os.pathsep)


def test_remove_takes_the_entry_out_of_this_process(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/opt/tools"]))
    remove_path(Path("/opt/tools"), _store=FakeStore())
    assert os.environ["PATH"].split(os.pathsep) == ["/usr/bin"]


def test_remove_leaves_an_unrelated_process_path_untouched(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/opt/other"]))
    remove_path(Path("/opt/tools"), _store=FakeStore())
    assert os.environ["PATH"].split(os.pathsep) == ["/usr/bin", "/opt/other"]


# ---------------------------------------------------------------------------
# the real store
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32", reason="the refusal only applies off windows"
)
def test_the_real_store_refuses_to_run_off_windows():
    with pytest.raises(RuntimeError):
        RegistryUserPathStore()

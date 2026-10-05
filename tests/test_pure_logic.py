"""Phase 1: pure logic, called directly. No filesystem, no sandbox.

Asserting behaviour rather than wording throughout.
"""

import json

import pytest

from auth import AuthModes
from collection_utils import merge_collections_to_set, remove_where, safe_remove
from hook_failure_types import HookFailure, HookSuccess
from load_config_map import parse
from load_config_map.parsers import JsonParser, TomllibParser
from merged_error import MergedError


# ---------------------------------------------------------------------------
# AuthModes  (regression: the duplicated "auto reject" branch)
# ---------------------------------------------------------------------------


def test_auto_reject_maps_to_auto_reject():
    assert AuthModes.from_str("auto reject") is AuthModes.AUTO_REJECT


def test_auto_approve_maps_to_auto_approve():
    # This is the branch that used to be unreachable.
    assert AuthModes.from_str("auto approve") is AuthModes.AUTO_APPROVE


@pytest.mark.parametrize("value", [None, "", "manual", "AUTO APPROVE", "nonsense"])
def test_anything_else_is_manual(value):
    assert AuthModes.from_str(value) is AuthModes.MANUAL


def test_all_three_modes_are_reachable():
    """Every enum member must be obtainable from its own string value."""
    for mode in AuthModes:
        assert AuthModes.from_str(mode.value) is mode


# ---------------------------------------------------------------------------
# collection_utils
# ---------------------------------------------------------------------------


def test_merge_is_a_set_union():
    assert merge_collections_to_set(["a", "b"], ["b", "c"]) == {"a", "b", "c"}


def test_merge_with_no_collections_is_empty():
    assert merge_collections_to_set() == set()


def test_safe_remove_removes_when_present():
    out = ["a", "b"]
    safe_remove(out, "a")
    assert out == ["b"]


def test_safe_remove_is_a_noop_when_absent():
    out = ["a"]
    safe_remove(out, "z")
    assert out == ["a"]


def test_remove_where_drops_every_match():
    out = [1, 2, 3, 4, 5, 6]
    remove_where(out, lambda v: v % 2 == 0)
    assert out == [1, 3, 5]


# ---------------------------------------------------------------------------
# hook_failure_types
# ---------------------------------------------------------------------------


def test_hook_success():
    assert HookSuccess().success() is True
    assert isinstance(HookSuccess().get_message(), str)


def test_hook_failure_keeps_its_message():
    result = HookFailure("it went wrong")
    assert result.success() is False
    assert result.get_message() == "it went wrong"


def test_hook_result_base_is_abstract():
    from hook_failure_types import HookResult

    base = HookResult()
    with pytest.raises(NotImplementedError):
        base.success()
    with pytest.raises(NotImplementedError):
        base.get_message()


# ---------------------------------------------------------------------------
# merged_error
# ---------------------------------------------------------------------------


def test_no_errors_by_default():
    assert MergedError().has_erred() is False


def test_add_error_if_only_fires_on_true():
    err = MergedError()
    err.add_error_if(False, "should not appear")
    assert err.errors == []
    err.add_error_if(True, "boom")
    assert err.errors == ["boom"]


def test_on_missing_toml_field_reports_each_absent_field():
    err = MergedError()
    err.on_missing_toml_field("executable_name", "build", {"command": "x"})
    err.on_missing_toml_field("command", "build", {"command": "x"})
    assert err.errors == ["missing 'executable_name' in [build]"]


def test_print_and_exit_does_not_exit_when_clean():
    MergedError().print_and_exit_if_erred()


def test_print_and_exit_exits_with_default_code(capsys):
    err = MergedError()
    err.add_error("bad thing")
    with pytest.raises(SystemExit) as excinfo:
        err.print_and_exit_if_erred()
    assert excinfo.value.code == 1
    assert "bad thing" in capsys.readouterr().out


def test_print_and_exit_honours_custom_code():
    err = MergedError()
    err.add_error("bad thing")
    with pytest.raises(SystemExit) as excinfo:
        err.print_and_exit_if_erred(exit_code=3)
    assert excinfo.value.code == 3


def test_multiple_errors_all_reported(capsys):
    err = MergedError()
    err.add_error("first")
    err.add_error("second")
    with pytest.raises(SystemExit):
        err.print_and_exit_if_erred()
    out = capsys.readouterr().out
    assert "first" in out and "second" in out


# ---------------------------------------------------------------------------
# load_config_map
# ---------------------------------------------------------------------------


def test_parse_toml(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[paths]\nbin_dir = "/opt/bin"\n')
    assert parse(f)["paths"]["bin_dir"] == "/opt/bin"


def test_parse_toml_with_explicit_parser(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[a]\nb = 1\n')
    assert parse(f, parser_override=TomllibParser())["a"]["b"] == 1


def test_parse_json(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"a": {"b": 2}}))
    assert parse(f, parser_override=JsonParser())["a"]["b"] == 2


def test_parse_unknown_suffix_returns_none(tmp_path):
    f = tmp_path / "c.ini"
    f.write_text("[a]\n")
    assert parse(f) is None


def test_parse_applies_defaults_for_missing_keys(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[paths]\nbin_dir = "/opt/bin"\n')
    merged = parse(f, defaults={"paths": {"install_dir": "/opt/lib"}})
    assert merged["paths"]["bin_dir"] == "/opt/bin"
    assert merged["paths"]["install_dir"] == "/opt/lib"


def test_parse_defaults_do_not_clobber_existing_values(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[paths]\nbin_dir = "/real/bin"\n')
    merged = parse(f, defaults={"paths": {"bin_dir": "/default/bin"}})
    assert merged["paths"]["bin_dir"] == "/real/bin"


def test_tomlkit_is_used_when_available(tmp_path):
    """Auto-detection prefers tomlkit for .toml, matching the documented behaviour."""
    f = tmp_path / "c.toml"
    f.write_text("[a]\nb = 1\n")
    try:
        import tomlkit  # noqa: F401
    except ImportError:
        pytest.skip("tomlkit not installed")
    from load_config_map.auto_detect_parser import detect_parser

    assert detect_parser(f).__class__.__name__ == "TomlkitParser"

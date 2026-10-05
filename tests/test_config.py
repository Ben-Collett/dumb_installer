"""Config and ConfigManager: path resolution and auth mode loading.

ConfigManager already accepts a platform wrapper for injection, so platform
branches are testable without being on that platform. Note this is a *unit*
test of the branch logic -- no real macOS or Windows is involved (see
TESTING_PLAN.md section 9).
"""

from pathlib import Path

import pytest

from auth import AuthModes
from config_manager import ConfigManager
from config_manager import _PlatformWrapper


class FakePlatform:
    """Stands in for _PlatformWrapper so platform branches are reachable."""

    def __init__(self, system="Linux", sudo_uid=None, env=None, home="/home/tester"):
        self._system = system
        self._sudo_uid = sudo_uid
        self._env = env or {}
        self._home = Path(home)
        self.mkdirs = []
        self.created = []

    def get_env(self, name):
        return self._env.get(name)

    def mkdir(self, path):
        self.mkdirs.append(path)
        Path(path).mkdir(parents=True, exist_ok=True)

    def exists(self, path):
        return Path(path).exists()

    @property
    def _is_on_windowns(self):
        return self._system == "Windows"

    @property
    def _is_on_linux(self):
        return self._system == "Linux"

    @property
    def _is_on_mac(self):
        return self._system == "Darwin"

    @property
    def _sudo_id(self):
        return self._sudo_uid


# ---------------------------------------------------------------------------
# Platform dir selection
# ---------------------------------------------------------------------------


def test_linux_default_uses_xdg_config_home():
    plat = FakePlatform(env={"XDG_CONFIG_HOME": "/custom/cfg"})
    mgr = ConfigManager("dumb_installer", _platform_wrapper=plat)
    assert mgr.find_config_dir_path() == Path("/custom/cfg/dumb_installer")


def test_linux_falls_back_to_dot_config(monkeypatch):
    # ConfigManager calls Path.home() directly rather than via the injected
    # wrapper, so the home directory has to be patched separately.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/home/tester")))
    plat = FakePlatform(env={})
    mgr = ConfigManager("dumb_installer", _platform_wrapper=plat)
    assert mgr.find_config_dir_path() == Path("/home/tester/.config/dumb_installer")


def test_macos_config_path(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/Users/tester")))
    plat = FakePlatform(system="Darwin")
    mgr = ConfigManager("dumb_installer", _platform_wrapper=plat)
    expected = Path("/Users/tester/Library/Application Support/dumb_installer")
    assert mgr.find_config_dir_path() == expected


def test_windows_config_path_from_appdata():
    plat = FakePlatform(system="Windows", env={"APPDATA": "C:/Users/t/AppData/Roaming"})
    mgr = ConfigManager("dumb_installer", _platform_wrapper=plat)
    assert mgr.find_config_dir_path() == Path("C:/Users/t/AppData/Roaming/dumb_installer")


def test_windows_falls_back_when_appdata_missing(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("C:/Users/t")))
    plat = FakePlatform(system="Windows", env={})
    mgr = ConfigManager("dumb_installer", _platform_wrapper=plat)
    assert mgr.find_config_dir_path() == Path("C:/Users/t/AppData/Roaming/dumb_installer")


def test_unsupported_platform_raises():
    plat = FakePlatform(system="Plan9")
    mgr = ConfigManager("dumb_installer", _platform_wrapper=plat)
    with pytest.raises(RuntimeError):
        mgr.find_config_dir_path()


def test_path_override_variable_wins():
    plat = FakePlatform(env={"DUMB_CFG": "/override/here"})
    mgr = ConfigManager(
        "dumb_installer",
        path_override_variable_name="DUMB_CFG",
        _platform_wrapper=plat,
    )
    assert mgr.find_config_dir_path() == Path("/override/here")


def test_fallback_when_override_variable_unset():
    plat = FakePlatform(env={"XDG_CONFIG_HOME": "/xdg"})
    mgr = ConfigManager(
        "dumb_installer",
        path_override_variable_name="DUMB_MISSING",
        _platform_wrapper=plat,
    )
    assert mgr.find_config_dir_path() == Path("/xdg/dumb_installer")


# ---------------------------------------------------------------------------
# sudo behaviour
# ---------------------------------------------------------------------------


def test_separate_sudo_config_uses_etc():
    plat = FakePlatform(sudo_uid="1000")
    mgr = ConfigManager(
        "dumb_installer", separate_sudo_config=True, _platform_wrapper=plat
    )
    assert mgr.find_config_dir_path() == Path("/etc/dumb_installer")


def test_without_separate_sudo_config_uses_own_config_home():
    """With separate_sudo_config off, a sudo'd run still uses the config home
    rather than /etc -- the flag, not the sudo id, decides this."""
    plat = FakePlatform(sudo_uid="1000", env={"XDG_CONFIG_HOME": "/home/tester/.config"})
    mgr = ConfigManager(
        "dumb_installer", separate_sudo_config=False, _platform_wrapper=plat
    )
    assert mgr.find_config_dir_path() == Path("/home/tester/.config/dumb_installer")


def test_no_sudo_uses_home_config():
    plat = FakePlatform(sudo_uid=None, env={"XDG_CONFIG_HOME": "/home/tester/.config"})
    mgr = ConfigManager("dumb_installer", _platform_wrapper=plat)
    assert mgr.find_config_dir_path() == Path("/home/tester/.config/dumb_installer")


# ---------------------------------------------------------------------------
# Config loading (real toml on disk)
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    """Point config.config_path at a real file in tmp_path."""
    import config as config_module

    path = tmp_path / "config.toml"
    monkeypatch.setattr(config_module, "config_path", lambda: path)
    return path


def test_config_defaults_when_file_absent(cfg_path, monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module, "is_root", lambda: False)
    cfg = config_module.Config()
    assert cfg.binary_dir.name == "bin"
    assert cfg.project_install_dir.name == "dumb_builds"
    assert cfg.on_update_mode is AuthModes.MANUAL
    assert cfg.on_install_mode is AuthModes.MANUAL


def test_config_reads_paths_from_toml(cfg_path, monkeypatch):
    import config as config_module

    cfg_path.write_text(
        '[paths]\nbin_dir = "/opt/mybin"\nproject_install_dir = "/opt/mylib"\n'
    )
    monkeypatch.setattr(config_module, "is_root", lambda: True)
    cfg = config_module.Config()
    assert cfg.binary_dir == Path("/opt/mybin")
    assert cfg.project_install_dir == Path("/opt/mylib")


def test_config_reads_auth_modes(cfg_path, monkeypatch):
    import config as config_module

    cfg_path.write_text(
        'on_install_auth = "auto approve"\non_update_auth = "auto reject"\n'
    )
    monkeypatch.setattr(config_module, "is_root", lambda: True)
    cfg = config_module.Config()
    assert cfg.on_install_mode is AuthModes.AUTO_APPROVE
    assert cfg.on_update_mode is AuthModes.AUTO_REJECT


def test_config_defaults_to_root_dirs_under_sudo(cfg_path, monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module, "is_root", lambda: True)
    cfg = config_module.Config()
    assert cfg.binary_dir == Path("/usr/local/bin")
    assert cfg.project_install_dir == Path("/usr/lib/dumb_builds")


def test_config_defaults_to_user_dirs_without_sudo(cfg_path, monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module, "is_root", lambda: False)
    cfg = config_module.Config()
    assert cfg.binary_dir == Path("~/.local/bin").expanduser()
    assert cfg.project_install_dir == Path("~/.local/lib/dumb_builds").expanduser()


# ---------------------------------------------------------------------------
# create_initial_config
# ---------------------------------------------------------------------------


def test_create_initial_config_creates_file(cfg_path, monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module, "is_root", lambda: True)
    cfg = config_module.Config()
    created, path = cfg.create_initial_config()

    assert created is True
    assert path == cfg_path
    assert cfg_path.is_file()
    assert "/usr/local/bin" in cfg_path.read_text()


def test_create_initial_config_does_not_overwrite(cfg_path, monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module, "is_root", lambda: True)
    cfg_path.write_text("# hand written\n")
    cfg = config_module.Config()

    created, path = cfg.create_initial_config()

    assert created is False
    assert cfg_path.read_text() == "# hand written\n"


def test_created_config_round_trips(cfg_path, monkeypatch):
    """A config we generate must be readable by Config."""
    import config as config_module

    monkeypatch.setattr(config_module, "is_root", lambda: True)
    config_module.Config().create_initial_config()

    reloaded = config_module.Config()
    assert reloaded.binary_dir == Path("/usr/local/bin")
    assert reloaded.project_install_dir == Path("/usr/lib/dumb_builds")


def test_executable_and_install_path_helpers(cfg_path, monkeypatch):
    import config as config_module

    cfg_path.write_text(
        '[paths]\nbin_dir = "/b"\nproject_install_dir = "/l"\n'
    )
    cfg = config_module.Config()
    assert cfg.executable_path("tool") == Path("/b/tool")
    assert cfg.install_path("tool") == Path("/l/tool")


# ---------------------------------------------------------------------------
# is_root
# ---------------------------------------------------------------------------


def test_is_root_reads_sudo_uid(monkeypatch):
    import config as config_module

    monkeypatch.setenv("SUDO_UID", "1000")
    assert config_module.is_root() is True

    monkeypatch.delenv("SUDO_UID", raising=False)
    assert config_module.is_root() is False


def test_real_platform_wrapper_env(monkeypatch):
    """The concrete wrapper reads the real environment."""
    wrapper = _PlatformWrapper()
    monkeypatch.setenv("DUMB_TEST_VAR", "value")
    assert wrapper.get_env("DUMB_TEST_VAR") == "value"
    monkeypatch.delenv("SUDO_UID", raising=False)
    assert wrapper._sudo_id is None

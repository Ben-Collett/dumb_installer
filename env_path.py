"""
Add and remove directories in the user's PATH environment variable.

Windows only: on windows the user's PATH is the registry value
``HKCU\\Environment\\Path``, and that is the thing these functions write.
Off windows there is no equivalent (linux keeps PATH in shell startup files,
which this module refuses to guess at), so the real store errors instead.
"""

import os
from pathlib import Path

from platform_utils import is_windows

_ENTRY_SEPARATOR = ";"
_ENVIRONMENT = "Environment"  # registry subkey of HKCU, and the broadcast name
_PATH_VALUE = "Path"


def split_path_entries(value: str | None) -> list[str]:
    """Split a PATH value into its raw entries, blanks included."""
    if not value:
        return []
    return value.split(_ENTRY_SEPARATOR)


def join_path_entries(entries: list[str]) -> str:
    return _ENTRY_SEPARATOR.join(entries)


def contains_entry(entries: list[str], target: str) -> bool:
    wanted = _normalize(target)
    return any(_normalize(entry) == wanted for entry in entries)


def add_entry(entries: list[str], target: str) -> list[str]:
    if contains_entry(entries, target):
        return list(entries)
    return [*entries, target]


def remove_entry(entries: list[str], target: str) -> list[str]:
    """Copy of entries with every entry pointing at target dropped."""
    wanted = _normalize(target)
    return [entry for entry in entries if _normalize(entry) != wanted]


def _normalize(entry: str) -> str:
    """Compare entries the way windows reads them: case and trailing
    separator do not make ``c:\\tools``, ``C:\\Tools\\`` different directories."""
    return entry.strip().rstrip("\\/").casefold()


def _apply_to_current_process(target: str, present: bool) -> None:
    """
    Mirror the change into this already-running process.

    The registry holds only the user's half of PATH, and only for processes
    started after the write; the installer may still want to run something
    out of `target` right now, so the running copy is kept in step as well.
    """
    current = os.environ.get("PATH")
    entries = [e for e in current.split(os.pathsep) if e] if current else []

    updated = add_entry(
        entries, target) if present else remove_entry(entries, target)
    if updated != entries:
        os.environ["PATH"] = os.pathsep.join(updated)


class UserPathStore:
    """Where the user's PATH value lives: read it, write it, announce it."""

    def read(self) -> str:
        raise NotImplementedError

    def write(self, value: str) -> None:
        raise NotImplementedError

    def broadcast(self) -> None:
        raise NotImplementedError


class RegistryUserPathStore(UserPathStore):
    def __init__(self):
        if not is_windows():
            raise RuntimeError(
                "PATH can only be edited on windows: the user's PATH is a "
                "registry value there"
            )
        import winreg  # windows only, so it cannot be imported at module level

        self._winreg = winreg

    def read(self) -> str:
        winreg = self._winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _ENVIRONMENT, 0, winreg.KEY_READ
            ) as key:
                value, _kind = winreg.QueryValueEx(key, _PATH_VALUE)
        except FileNotFoundError:
            # no key, or no Path value under it: the user has no PATH yet
            return ""
        return value if isinstance(value, str) else ""

    def write(self, value: str) -> None:
        winreg = self._winreg
        # CreateKeyEx so a user who has never had a PATH gets one.
        # REG_EXPAND_SZ keeps entries like %USERPROFILE%\\bin expanding.
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _ENVIRONMENT, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, _PATH_VALUE, 0, winreg.REG_EXPAND_SZ, value)

    def broadcast(self) -> None:
        """Tell running programs to reload their environment (WM_SETTINGCHANGE).

        Without it every already-open terminal keeps the stale PATH until
        the next logon.
        """
        import ctypes

        HWND_BROADCAST = 0xFFFF  # sentinel value sends to every top level window
        WM_SETTINGCHANGE = 0x001A  # singlast that a setting changed
        SMTO_ABORTIFHUNG = 0x0002
        TIMEOUT_MS = 5_000

        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [
            ctypes.c_void_p,  # hWnd
            ctypes.c_uint,  # Msg
            ctypes.c_size_t,  # wParam
            ctypes.c_wchar_p,  # lParam
            ctypes.c_uint,  # fuFlags
            ctypes.c_uint,  # uTimeout
            ctypes.POINTER(ctypes.c_size_t),  # lpdwResult
        ]
        send.restype = ctypes.c_size_t

        result = ctypes.c_size_t(0)
        send(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            _ENVIRONMENT,
            SMTO_ABORTIFHUNG,
            TIMEOUT_MS,
            ctypes.byref(result),
        )


def add_path(path: Path, _store: UserPathStore | None = None) -> None:
    """
    add's the path to the users environment PATH varaibel

    errors on linux, only works on windows (see RegistryUserPathStore);
    `_store` swaps in a stand-in for testing.
    """
    store = _store if _store is not None else RegistryUserPathStore()
    target = str(path)

    current = split_path_entries(store.read())
    updated = add_entry(current, target)
    if updated != current:
        store.write(join_path_entries(updated))
        store.broadcast()

    _apply_to_current_process(target, present=True)


def remove_path(path: Path, _store: UserPathStore | None = None) -> None:
    """
    remove's the path to the users environment PATH varaibel

    errors on linux, only works on windows (see RegistryUserPathStore);
    `_store` swaps in a stand-in for testing.
    """
    store = _store if _store is not None else RegistryUserPathStore()
    target = str(path)

    current = split_path_entries(store.read())
    updated = remove_entry(current, target)
    if updated != current:
        store.write(join_path_entries(updated))
        store.broadcast()

    _apply_to_current_process(target, present=False)

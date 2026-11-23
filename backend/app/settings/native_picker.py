from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlsplit


class NativePickerUnavailable(RuntimeError):
    pass


_picker_slot = BoundedSemaphore(1)


def _local_origin(origin: str | None) -> bool:
    if not origin:
        return False
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return False
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            return False
        _ = parsed.port
        host = parsed.hostname.lower()
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _command() -> list[str]:
    directory = Path(__file__).parent
    if sys.platform == "darwin":
        executable = shutil.which("osascript")
        if executable:
            return [executable, "-l", "JavaScript", str(directory / "native_picker_macos.js")]
    elif sys.platform == "win32":
        executable = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if executable:
            return [executable, "-NoProfile", "-STA", "-File", str(directory / "native_picker_windows.ps1")]
    elif sys.platform.startswith("linux"):
        return [sys.executable, str(directory / "native_picker_linux.py")]
    raise NativePickerUnavailable("The native folder chooser is not available on this platform")


def choose_folders(public_origin: str | None) -> list[str]:
    if os.getenv("IIHS_NATIVE_FOLDER_PICKER") != "1" or not _local_origin(public_origin):
        raise NativePickerUnavailable("Native folder selection is disabled; enable it only for a local desktop deployment")
    if not _picker_slot.acquire(blocking=False):
        raise NativePickerUnavailable("A native folder chooser is already open")
    try:
        try:
            allowed = ("PATH", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
                       "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "DISPLAY",
                       "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
                       "XDG_DATA_DIRS", "DBUS_SESSION_BUS_ADDRESS")
            environment = {name: os.environ[name] for name in allowed if name in os.environ}
            result = subprocess.run(_command(), capture_output=True, text=True, timeout=300, check=False,
                                    env=environment, encoding="utf-8")
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            raise NativePickerUnavailable("The native folder chooser could not be opened") from exc
        if result.returncode:
            raise NativePickerUnavailable("The native folder chooser could not be opened; check desktop and platform helper availability")
        try:
            paths = json.loads(result.stdout)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise NativePickerUnavailable("The native folder chooser returned an invalid response") from exc
        if not isinstance(paths, list) or len(paths) > 100 or any(
            not isinstance(path, str) or not path or len(path) > 32768 for path in paths
        ):
            raise NativePickerUnavailable("The native folder chooser returned an invalid response")
        return paths
    finally:
        _picker_slot.release()

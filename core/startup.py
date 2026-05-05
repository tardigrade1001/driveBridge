"""
DriveBridge startup registration for Windows.
Adds/removes a shortcut in the Windows Startup folder.
"""
import os
from pathlib import Path


def _startup_folder():
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path():
    return _startup_folder() / "DriveBridge.bat"


def is_registered():
    return _shortcut_path().exists()


def register():
    """Add DriveBridge to Windows startup."""
    script  = Path(__file__).parent.parent / "main.py"
    bat     = (
        f'@echo off\n'
        f'where pythonw >nul 2>&1 && (\n'
        f'    start "" pythonw "{script}"\n'
        f') || (\n'
        f'    start "" python "{script}"\n'
        f')\n'
    )
    try:
        _shortcut_path().write_text(bat, encoding="utf-8")
        return True
    except Exception as e:
        return False


def unregister():
    """Remove DriveBridge from Windows startup."""
    try:
        _shortcut_path().unlink(missing_ok=True)
        return True
    except Exception:
        return False

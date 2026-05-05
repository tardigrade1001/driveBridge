"""
DriveBridge startup registration for Windows.
Adds/removes a shortcut in the Windows Startup folder.
"""
import os
import sys
from pathlib import Path


def _startup_folder():
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path():
    return _startup_folder() / "DriveBridge.bat"


def is_registered():
    return _shortcut_path().exists()


def _pythonw() -> str:
    """Return pythonw.exe path (no console window) derived from the current interpreter."""
    exe = Path(sys.executable)
    candidate = exe.parent / "pythonw.exe"
    return str(candidate) if candidate.exists() else str(exe)


def register():
    """Add DriveBridge to Windows startup."""
    python  = _pythonw()
    script  = Path(__file__).parent.parent / "main.py"
    bat     = f'@echo off\nstart "" "{python}" "{script}"\n'
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

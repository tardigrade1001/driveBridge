"""
DriveBridge logger.
Keeps a rolling in-memory log + writes to drivebridge.log file.
File is capped at 512 KB across 2 backups via RotatingFileHandler.
"""
import datetime
import logging
import logging.handlers
from pathlib import Path
from collections import deque

LOG_FILE    = Path(__file__).parent.parent / "drivebridge.log"
MAX_ENTRIES = 200   # in-memory rolling window
_entries    = deque(maxlen=MAX_ENTRIES)

_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
)
_file_logger = logging.getLogger("drivebridge")
_file_logger.addHandler(_handler)
_file_logger.setLevel(logging.DEBUG)
_file_logger.propagate = False


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def info(message: str):
    _log("INFO", message)

def success(message: str):
    _log("OK", message)

def warning(message: str):
    _log("WARN", message)

def error(message: str):
    _log("ERROR", message)

def _log(level: str, message: str):
    entry = {"time": _now(), "level": level, "message": message}
    _entries.append(entry)
    line = f"[{entry['time']}] [{level:<5}] {message}"
    _file_logger.info(line)

def get_entries(n=50):
    """Return last n entries, newest first."""
    entries = list(_entries)
    return list(reversed(entries[-n:]))

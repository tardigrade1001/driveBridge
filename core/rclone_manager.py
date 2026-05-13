"""
rclone wrapper for DriveBridge.
All rclone interactions go through here.
Includes optional watchdog-based live sync and error recovery.
"""
import datetime
import glob
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from core import config
from core import logger

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


class _SyncHandler(FileSystemEventHandler):
    """Debounces rapid file changes before triggering sync."""
    def __init__(self, trigger_fn, debounce_seconds=4):
        super().__init__()
        self._trigger  = trigger_fn
        self._debounce = debounce_seconds
        self._timer    = None
        self._lock     = threading.Lock()

    def _should_ignore(self, event):
        path = getattr(event, 'dest_path', event.src_path)
        name = os.path.basename(path).lower()
        if name.startswith("~$") or name.endswith(".tmp") or name in ("desktop.ini", "thumbs.db", ".bisync_initialized"):
            return True
        return False

    def _schedule(self, event=None):
        if event and self._should_ignore(event):
            return
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self._trigger)
            self._timer.daemon = True
            self._timer.start()

    def on_created(self, event):  self._schedule(event)
    def on_modified(self, event): self._schedule(event)
    def on_deleted(self, event):  self._schedule(event)
    def on_moved(self, event):    self._schedule(event)


class RcloneManager:
    def __init__(self, ui_root=None):
        self.ui_root        = ui_root
        self.status         = "idle"
        self.last_error     = None
        self.last_synced    = None       # datetime of last successful sync
        self._observer      = None
        self._sync_lock        = threading.Lock()
        self._recent_lock      = threading.Lock()  # guards recent_files list
        self._retry_count      = 0
        self._max_retries      = 3
        self.live_progress     = ""
        self.recent_files      = []
        self._sync_process     = None
        self.is_paused         = False


    def toggle_pause(self):
        if self.is_paused:
            self.is_paused = False
            self.status = "idle"
            logger.info("DriveBridge resumed sync operations.")
        else:
            self.is_paused = True
            self.status = "paused"
            logger.info("DriveBridge paused. Terminating active syncs.")
            self.stop_sync()

    # ─────────────────────────────────────────────────────────
    #  BISYNC — lock-protected, with retry + backoff
    # ─────────────────────────────────────────────────────────
    def _run_bisync(self, local_path: Path, remote: str,
                    on_complete=None, _retry=0):

        if getattr(self, "is_paused", False):
            return

        if not self._sync_lock.acquire(blocking=False):
            logger.info("Sync already running — skipping duplicate.")
            if on_complete:
                on_complete(False, "Sync already in progress")
            return

        marker      = local_path / ".bisync_initialized"
        resync_flag = [] if marker.exists() else ["--resync"]

        cmd = [
            config.load_config()["rclone_path"],
            "bisync", str(local_path), remote,
            "--resilient",
            "--recover",
            "--ignore-listing-checksum",
            "--checkers", "64",
            "--transfers", "32",
            "--modify-window", "1s",
            "--conflict-resolve", "newer",
            "--conflict-loser", "delete",
            "--max-lock", "2m",
            "--exclude", "desktop.ini",
            "--exclude", "Thumbs.db",
            "--exclude", "~$*",
            "--exclude", "*.tmp",
            "--exclude", ".bisync_initialized",
            "--progress",
            "--verbose",
        ] + resync_flag

        prev_status = self.status
        self.status = "syncing"
        self.live_progress  = ""
        logger.info(f"Syncing {local_path.name} ↔ {remote}")

        def worker():
            owns_lock = True
            try:
                # Nuke orphaned lock files so sudden app shutdowns never stall future syncs.
                try:
                    lck_dir = os.path.expandvars(r"%LOCALAPPDATA%\rclone\bisync")
                    for lock_file in glob.glob(os.path.join(lck_dir, "*.lck")):
                        try: os.remove(lock_file)
                        except Exception: pass
                except Exception: pass

                cflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=cflags, encoding='utf-8', errors='replace')
                self._sync_process = process

                out_err_list = []
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    line_clean = ansi_escape.sub('', line).strip()
                    if line_clean:
                        line_clean = line_clean.replace("Ki", "KB").replace("Mi", "MB").replace("Gi", "GB").replace("Ti", "TB")
                        out_err_list.append(line_clean)
                        # Extract the meaningful file or percentage chunks
                        if line_clean.startswith("*") or line_clean.startswith("Transferred:"):
                            if "0 B / 0 B" in line_clean and "0 B/s" in line_clean:
                                self.live_progress = "Scanning for file changes and hashing..."
                            else:
                                self.live_progress = line_clean

                        # Scrape file history
                        if ": Copied" in line_clean or ": Deleted" in line_clean or ": Updated" in line_clean:
                            try:
                                # Strip timestamp + log level prefix if present (e.g. "2026/05/05 12:00:00 INFO  : ")
                                if "INFO  : " in line_clean:
                                    msg = line_clean.split("INFO  : ", 1)[1]
                                elif "NOTICE: " in line_clean:
                                    msg = line_clean.split("NOTICE: ", 1)[1]
                                else:
                                    msg = line_clean
                                # fname is everything before the last ": Action" segment
                                fname = re.split(r": (?:Copied|Deleted|Updated)", msg)[0].strip()
                                if not fname:
                                    raise ValueError("empty fname")

                                action = "Deleted" if "Deleted" in line_clean else "Synced"

                                new_entry = {"name": fname, "action": action, "time": time.strftime("%H:%M")}
                                with self._recent_lock:
                                    if not self.recent_files or self.recent_files[0]["name"] != fname:
                                        self.recent_files = ([new_entry] + self.recent_files)[:10]
                            except Exception:
                                pass

                process.wait()
                result_returncode = process.returncode
                out_err = "\n".join(out_err_list)

                if self.is_paused:
                    # Forcefully terminated by Pause — return cleanly in silence
                    return

                if result_returncode not in (0, 9) and "too many deletes" in out_err:
                    if config.load_config().get("confirm_deletions", True):
                        import ctypes
                        ret = ctypes.windll.user32.MessageBoxW(0,
                            "DriveBridge detected you deleted a large volume of files.\nDo you want to permanently sync these deletions to Google Drive?",
                            "DriveBridge - Confirm Mass Deletions", 4148)
                        if ret == 6:  # IDYES
                            logger.info("User confirmed mass deletion.")
                            force_result = subprocess.run(cmd + ["--force"], check=False, capture_output=True, text=True, creationflags=cflags)
                            result_returncode = force_result.returncode  # use the force-run's actual exit code
                        else:
                            logger.info("Mass deletion cancelled by user.")
                            if on_complete: on_complete(False, "Mass deletion cancelled by user")
                            return
                    else:
                        logger.info("Auto-forcing mass deletion (confirm_deletions is off).")
                        force_result = subprocess.run(cmd + ["--force"], check=False, capture_output=True, text=True, creationflags=cflags)
                        result_returncode = force_result.returncode  # use the force-run's actual exit code

                if result_returncode in (0, 9):
                    marker.touch()
                    self.last_synced  = datetime.datetime.now()
                    self._retry_count = 0
                    self.status       = prev_status
                    self.live_progress = ""
                    logger.success(f"Synced {local_path.name}")

                    # Automatically Scan for Conflicts
                    if local_path.exists():
                        conflicts = [f for f in local_path.rglob("*conflict*") if ".." in f.name]
                        if conflicts:
                            logger.warning(f"Detected {len(conflicts)} conflict files! Launching resolver UI.")
                            try:
                                from ui import conflict_ui
                                if self.ui_root:
                                    conflict_ui.ConflictResolver.open(self.ui_root, self, local_path, conflicts)
                            except Exception as e:
                                logger.error(f"Failed to open conflict UI: {e}")

                    if on_complete:
                        on_complete(True, None)

                else:
                    self.live_progress = ""
                    fatal_lines = [l for l in out_err_list if "ERROR" in l or "NOTICE" in l or "Failed" in l]
                    detail = fatal_lines[-1].split("NOTICE:")[-1].strip() if fatal_lines else ""

                    err = f"rclone bisync exited {result_returncode}"
                    if detail: err += f" — {detail}"

                    self.last_error = err

                    # Retry with backoff — interruptible by Pause
                    if _retry < self._max_retries:
                        delay = 5 * (2 ** _retry)   # 5s, 10s, 20s
                        logger.warning(f"Sync failed (attempt {_retry+1}) — retrying in {delay}s")
                        self.status = prev_status
                        self._sync_lock.release()
                        owns_lock = False
                        # Sleep in 1-second ticks so Pause can interrupt the wait
                        for _ in range(delay):
                            if self.is_paused:
                                return
                            time.sleep(1)
                        self._run_bisync(local_path, remote,
                                         on_complete=on_complete,
                                         _retry=_retry + 1)
                        return
                    else:
                        logger.error(f"Sync failed after {self._max_retries} retries: {err}")
                        # Repressing minor error red flashes
                        # self.status = "error"
                        if on_complete:
                            on_complete(False, err)

            except Exception as e:
                self.last_error = str(e)
                # Repressing exception error red flashes
                # self.status = "error"
                logger.error(f"Sync exception: {e}")
                if on_complete:
                    on_complete(False, str(e))
            finally:
                if owns_lock:
                    try:
                        self._sync_lock.release()
                    except RuntimeError:
                        pass  # just in case

        threading.Thread(target=worker, daemon=True).start()

    def stop_sync(self):
        if self._sync_process:
            try:
                self._sync_process.terminate()
                self._sync_process = None
            except Exception: pass

    # ─────────────────────────────────────────────────────────
    #  FULL BISYNC (PC mode)
    # ─────────────────────────────────────────────────────────
    def full_bisync(self, on_complete=None):
        cfg    = config.load_config()
        local  = Path(cfg["local_folder"])
        remote = f"{cfg['remote_name']}:{cfg['drive_folder']}"
        self._run_bisync(local, remote, on_complete=on_complete)

    # ─────────────────────────────────────────────────────────
    #  WATCHDOG
    # ─────────────────────────────────────────────────────────
    def start_watch(self):
        if not WATCHDOG_AVAILABLE:
            self.last_error = "watchdog not installed — run: pip install watchdog"
            self.status = "error"
            logger.error("watchdog not installed")
            return False

        if self._observer and self._observer.is_alive():
            return True

        cfg   = config.load_config()
        local = Path(cfg["local_folder"])
        if not local.exists():
            self.last_error = f"Local folder not found: {local}"
            self.status = "error"
            logger.error(f"Watchdog: folder not found: {local}")
            return False

        handler  = _SyncHandler(trigger_fn=self.full_bisync, debounce_seconds=4)
        observer = Observer()
        observer.schedule(handler, str(local), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer
        logger.success(f"Watchdog watching {local}")
        return True

    def stop_watch(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("Watchdog stopped.")

    def is_watching(self):
        return self._observer is not None and self._observer.is_alive()

    # ─────────────────────────────────────────────────────────
    #  LIST DRIVE FOLDERS
    # ─────────────────────────────────────────────────────────
    def list_drive_folders(self, path=""):
        cfg = config.load_config()
        src = f"{cfg['remote_name']}:{cfg['drive_folder']}"
        if path:
            src = f"{src}/{path}"
        cmd = [cfg["rclone_path"], "lsf", "--dirs-only", src]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return [line.rstrip("/") for line in result.stdout.strip().split("\n") if line]
        except subprocess.CalledProcessError as e:
            self.last_error = str(e)
            return []

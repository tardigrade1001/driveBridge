"""
rclone wrapper for DriveBridge.
All rclone interactions go through here.
Includes optional watchdog-based live sync and error recovery.
"""
import datetime
import glob
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from core import config
from core import logger

HISTORY_FILE = Path(__file__).parent.parent / "drivebridge_activity.json"

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


class _SyncHandler(FileSystemEventHandler):
    """Debounces rapid file changes before triggering sync."""
    def __init__(self, upload_fn, reconcile_fn, debounce_seconds=4):
        super().__init__()
        self._upload = upload_fn
        self._reconcile = reconcile_fn
        self._debounce = debounce_seconds
        self._timers = {}
        self._reconcile_timer = None
        self._lock     = threading.Lock()

    def _should_ignore(self, event):
        path = getattr(event, 'dest_path', None) or event.src_path
        name = os.path.basename(path).lower()
        if name.startswith("~$") or name.endswith(".tmp") or name in ("desktop.ini", "thumbs.db", ".bisync_initialized"):
            return True
        return False

    def _schedule_upload(self, event):
        if event and self._should_ignore(event):
            return
        if event.is_directory:
            return
        path = getattr(event, 'dest_path', None) or event.src_path
        with self._lock:
            old_timer = self._timers.pop(path, None)
            if old_timer:
                old_timer.cancel()
            timer = threading.Timer(self._debounce, self._fire_upload, args=(path,))
            timer.daemon = True
            self._timers[path] = timer
            timer.start()

    def _fire_upload(self, path):
        with self._lock:
            self._timers.pop(path, None)
        self._upload(path)

    def _schedule_reconcile(self):
        with self._lock:
            if self._reconcile_timer:
                self._reconcile_timer.cancel()
            self._reconcile_timer = threading.Timer(self._debounce, self._reconcile)
            self._reconcile_timer.daemon = True
            self._reconcile_timer.start()

    def on_created(self, event):  self._schedule_upload(event)
    def on_modified(self, event): self._schedule_upload(event)
    def on_deleted(self, event):  self._schedule_reconcile()
    def on_moved(self, event):
        self._schedule_upload(event)
        self._schedule_reconcile()


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
        self.recent_files      = self._load_recent()
        self._sync_process     = None
        self.is_paused         = False
        self._pending_sync     = False
        self._pending_uploads  = set()
        self._pending_lock     = threading.Lock()
        self._upload_lock      = threading.Lock()
        self._last_local_change = time.monotonic()
        # A full bisync can touch local file metadata while reconciling the
        # tree.  Do not turn those reconciliation events back into quick
        # uploads.  Keep a short grace period because Windows can deliver the
        # resulting filesystem notifications after rclone exits.
        self._watch_suppressed_until = 0.0
        self.quick_upload_active = False
        self.quick_upload_file = ""
        self.last_quick_synced = None


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

                                self._record_recent(fname, action)
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
                    self._watch_suppressed_until = time.monotonic() + 10
                    self._drain_pending_work()

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

    def request_reconcile(self):
        """Run one full sync, preserving the request if other work is active."""
        if self._sync_lock.locked():
            self._pending_sync = True
            logger.info("Full reconciliation queued after active sync.")
        else:
            self.full_bisync()

    def fast_upload(self, path):
        """Queue one changed local file without scanning the entire tree."""
        # bisync is already reconciling this tree.  Its metadata updates can
        # produce watchdog modified events; feeding those back into copyto is
        # the duplicate-upload loop.  The reconciliation pass is the source
        # of truth while it holds this lock, and the grace period catches late
        # Windows notifications after it exits.
        if self._sync_lock.locked() or time.monotonic() < self._watch_suppressed_until:
            return

        self._last_local_change = time.monotonic()
        cfg = config.load_config()
        local_root = Path(cfg["local_folder"])
        source = Path(path)
        try:
            source.relative_to(local_root)
        except ValueError:
            return
        if self.is_paused or not source.is_file():
            return
        with self._pending_lock:
            self._pending_uploads.add(str(source))
        self._drain_pending_work()

    def startup_reconcile_when_idle(self, quiet_seconds=15):
        """Give newly created files priority before the slow startup sweep."""
        while not self.is_paused:
            remaining = quiet_seconds - (time.monotonic() - self._last_local_change)
            if remaining <= 0:
                break
            time.sleep(min(1, remaining))
        if not self.is_paused:
            logger.info("Local activity quiet; starting startup reconciliation.")
            self.request_reconcile()

    def _drain_pending_work(self):
        if self.is_paused:
            return
        with self._pending_lock:
            uploads = list(self._pending_uploads)
            self._pending_uploads.clear()
        if uploads:
            if self._sync_lock.locked():
                with self._pending_lock:
                    self._pending_uploads.update(uploads)
                return
            if not self._upload_lock.acquire(blocking=False):
                with self._pending_lock:
                    self._pending_uploads.update(uploads)
                return
            threading.Thread(target=self._run_fast_uploads,
                             args=(uploads,), daemon=True).start()
        elif self._pending_sync and not self._sync_lock.locked():
            self._pending_sync = False
            self.full_bisync()

    def _run_fast_uploads(self, paths):
        try:
            self.quick_upload_active = True
            cfg = config.load_config()
            local_root = Path(cfg["local_folder"])
            remote_root = f"{cfg['remote_name']}:{cfg['drive_folder']}"
            cflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            for index, raw_path in enumerate(paths):
                if self._sync_lock.locked():
                    with self._pending_lock:
                        self._pending_uploads.update(paths[index:])
                    break
                source = Path(raw_path)
                if self.is_paused or not source.is_file():
                    continue
                relative = source.relative_to(local_root).as_posix()
                self.quick_upload_file = relative
                size = source.stat().st_size
                started = time.monotonic()
                logger.info(f"Quick checking {relative}")
                result = subprocess.run(
                    [cfg["rclone_path"], "copyto", str(source),
                     f"{remote_root}/{relative}", "--modify-window", "1s",
                     "--no-traverse", "--checksum", "-vv"],
                    capture_output=True, text=True, creationflags=cflags)
                rclone_output = f"{result.stdout}\n{result.stderr}".lower()
                if result.returncode == 0:
                    if "unchanged skipping" in rclone_output:
                        logger.info(f"Quick skipped unchanged {relative}")
                    else:
                        logger.success(f"Quick synced {relative}")
                        self.last_quick_synced = datetime.datetime.now()
                        self._record_recent(relative, "Synced", size=size,
                                            duration=time.monotonic() - started)
                else:
                    detail = (result.stderr or result.stdout).strip()
                    self.last_error = f"Quick upload failed for {relative}: {detail}"
                    logger.error(self.last_error)
                    self._pending_sync = True
        finally:
            self.quick_upload_active = False
            self.quick_upload_file = ""
            self._upload_lock.release()
            self._drain_pending_work()

    def _record_recent(self, name, action, size=None, duration=None):
        entry = {
            "name": name,
            "action": action,
            "time": time.strftime("%H:%M"),
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "size": size,
            "duration": round(duration, 1) if duration is not None else None,
        }
        with self._recent_lock:
            self.recent_files = [e for e in self.recent_files if e["name"] != name]
            self.recent_files = ([entry] + self.recent_files)[:10]
            snapshot = list(self.recent_files)
        try:
            temp = HISTORY_FILE.with_suffix(".tmp")
            temp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            os.replace(temp, HISTORY_FILE)
        except Exception as exc:
            logger.warning(f"Could not save activity history: {exc}")

    @staticmethod
    def _load_recent():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data[:10] if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def pending_upload_count(self):
        with self._pending_lock:
            return len(self._pending_uploads)

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

        handler = _SyncHandler(upload_fn=self.fast_upload,
                               reconcile_fn=self.request_reconcile,
                               debounce_seconds=4)
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

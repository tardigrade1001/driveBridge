"""
DriveBridge — system tray app.
Single click → activity feed
Double click → settings
"""
import threading
import time
from PIL import Image, ImageDraw
import pystray

from core import config
from core import logger
from core import startup
from core.rclone_manager import RcloneManager, WATCHDOG_AVAILABLE
from ui.settings_gui import SettingsWindow
from ui.activity_feed import ActivityFeed
from ui.wizard import run_if_needed


class DriveBridgeApp:
    def __init__(self):
        import customtkinter as ctk
        self.root          = ctk.CTk()
        self.root.withdraw()  # Hide the persistent master window
        self.rclone        = RcloneManager(self.root)
        self.icon          = None
        self._elapsed_mins = 0
        self._stopping     = False

    # ─────────────────────────────────────────────────────────
    #  Icon

    def _make_icon(self, color):
        import os
        from PIL import Image, ImageDraw
        from core import config

        custom_icon = config.load_config().get("custom_icon_path", "")
        if custom_icon and os.path.exists(custom_icon):
            try:
                return Image.open(custom_icon).convert("RGBA").resize((64, 64))
            except Exception:
                pass

        img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Left Cloud
        draw.ellipse((4,  30, 24, 48), fill=color)
        draw.ellipse((8,  20, 28, 42), fill=color)
        draw.ellipse((14, 32, 30, 50), fill=color)

        # Right Cloud
        draw.ellipse((34, 32, 50, 50), fill=color)
        draw.ellipse((36, 20, 56, 42), fill=color)
        draw.ellipse((40, 30, 60, 48), fill=color)

        # Wooden bridge connecting them
        wood_dark = "#5c3a21"
        wood_lite = "#8b5a2b"

        # Bridge deck
        draw.line((18, 38, 46, 38), fill=wood_dark, width=5)
        # Handrail
        draw.line((20, 30, 44, 30), fill=wood_lite, width=3)
        # Vertical Posts
        for x in (22, 28, 34, 40):
            draw.line((x, 30, x, 36), fill=wood_lite, width=2)

        return img

    def _icon_color(self):
        return {
            "idle":     "#888888",
            "paused":   "#8888aa",
            "syncing":  "#e0e0e0",   # white-ish instead of purple
            "error":    "#e05050",
        }.get(self.rclone.status, "#888888")

    def _status_text(self, item=None):
        cfg  = config.load_config()
        mode = cfg.get("sync_mode", "interval")
        extra = ""
        if self.rclone.is_paused:
            extra = " [paused]"
        else:
            if mode == "watchdog":
                extra = " [watching]" if self.rclone.is_watching() else " [watchdog off]"
            elif mode == "interval":
                interval  = int(cfg.get("sync_interval_minutes", 30))
                remaining = max(0, interval - self._elapsed_mins)
                extra = f" [sync in {remaining}m]"
            elif mode == "both":
                extra = " [watch+interval]" if self.rclone.is_watching() else " [interval only]"
        last = self.rclone.last_synced
        last_str = f" · last {last.strftime('%H:%M')}" if last else ""
        return f"DriveBridge · {self.rclone.status}{extra}{last_str}"

    # ─────────────────────────────────────────────────────────
    #  Windows toast notification
    # ─────────────────────────────────────────────────────────
    def _notify(self, title, message):
        from utils import notify_utils
        notify_utils.show_toast(title, message)

    # ─────────────────────────────────────────────────────────
    #  Menu / click actions
    # ─────────────────────────────────────────────────────────
    def _on_single_click(self, icon, item=None):
        ActivityFeed.open(self.root, self.rclone)

    def _on_double_click(self, icon):
        self._open_settings(icon, None)

    def _open_settings(self, icon, item):
        def _apply():
            if not self.rclone.is_paused:
                self._apply_sync_mode()
        SettingsWindow.open(self.root, self.rclone, on_close_callback=_apply)

    def _on_toggle_pause(self, icon, item):
        # Delegate entirely to rclone so Activity Feed and tray stay in sync
        self.rclone.toggle_pause()
        if self.rclone.is_paused:
            self.rclone.stop_watch()
            self._notify("DriveBridge", "Syncing paused.")
        else:
            self._apply_sync_mode()
            self._notify("DriveBridge", "Syncing resumed.")

    def _on_sync_now(self, icon=None, item=None):
        def done(success, err):
            if success:
                self._notify("DriveBridge", "Sync complete ✓")
            else:
                self._notify("DriveBridge", f"Sync failed: {err}")
        self.rclone.full_bisync(on_complete=done)
        self._elapsed_mins = 0

    def _on_quit(self, icon, item):
        logger.info("DriveBridge shutting down.")
        self._stopping = True
        self.rclone.stop_sync()
        self.rclone.stop_watch()
        icon.stop()
        self.root.quit()

    # ─────────────────────────────────────────────────────────
    #  Sync mode
    # ─────────────────────────────────────────────────────────
    def _apply_sync_mode(self):
        cfg       = config.load_config()
        sync_mode = cfg.get("sync_mode", "interval")

        if sync_mode in ("watchdog", "both"):
            if not WATCHDOG_AVAILABLE:
                logger.error("watchdog not installed — run: pip install watchdog")
            elif not self.rclone.is_watching():
                ok = self.rclone.start_watch()
                if not ok:
                    logger.error(f"Watchdog failed: {self.rclone.last_error}")
        else:
            self.rclone.stop_watch()

    # ─────────────────────────────────────────────────────────
    #  Background loops
    # ─────────────────────────────────────────────────────────
    def _status_loop(self):
        # Only touch the tray icon when the status actually changes. Reassigning
        # icon.icon every tick churns GDI HICON handles and can race with / crash
        # pystray's message-loop thread over long uptimes.
        last = None
        while True:
            try:
                if self.icon:
                    key = (self._icon_color(), self._status_text())
                    if key != last:
                        self.icon.icon  = self._make_icon(key[0])
                        self.icon.title = key[1]
                        last = key
            except Exception:
                pass
            time.sleep(2)

    def _interval_sync_loop(self):
        while True:
            time.sleep(60)
            self._elapsed_mins += 1
            cfg       = config.load_config()
            sync_mode = cfg.get("sync_mode", "interval")
            interval  = int(cfg.get("sync_interval_minutes", 30))
            if sync_mode in ("interval", "both") and not self.rclone.is_paused:
                if self._elapsed_mins >= interval:
                    self._elapsed_mins = 0
                    self._on_sync_now()

    def _watchdog_guard_loop(self):
        while True:
            time.sleep(15)
            if self.rclone.is_paused:
                continue

            cfg = config.load_config()
            sync_mode = cfg.get("sync_mode", "interval")
            if sync_mode in ("watchdog", "both"):
                if WATCHDOG_AVAILABLE and not self.rclone.is_watching():
                    logger.warning("Watchdog died — restarting...")
                    self.rclone.start_watch()

    # ─────────────────────────────────────────────────────────
    #  Tray icon construction + supervision
    # ─────────────────────────────────────────────────────────
    def _build_icon(self):
        """Build a fresh pystray Icon (+ menu). Used at startup and to rebuild
        the icon if its message-loop thread ever dies."""
        menu = pystray.Menu(
            pystray.MenuItem(self._status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Activity Feed (Double Click)", self._on_single_click, default=True),
            pystray.MenuItem("Sync Now",   self._on_sync_now, enabled=lambda item: not self.rclone.is_paused),
            pystray.MenuItem(
                lambda item: "Resume Syncing" if self.rclone.is_paused else "Pause Syncing",
                self._on_toggle_pause
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings…",  self._open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",       self._on_quit),
        )
        icon = pystray.Icon(
            "drivebridge",
            self._make_icon(self._icon_color()),
            "DriveBridge",
            menu
        )
        # pystray limits single clicks on Windows; default=True menu item handles double-click reliably
        icon.on_activate = self._on_single_click
        return icon

    def _run_icon_supervised(self):
        """Keep the tray icon alive for the life of the process.

        pystray re-adds the icon on explorer restarts (it handles
        WM_TASKBARCREATED) — but only while its message loop is running. If that
        loop thread dies (e.g. a GDI hiccup over long uptime), the icon vanishes
        while the rest of the app keeps running. Here we block on icon.run(), and
        if it ever returns/crashes without us quitting, we rebuild and restart it.
        """
        while not self._stopping:
            try:
                self.icon.visible = True
                self.icon.run()          # blocks until icon.stop() or a crash
            except Exception as e:
                logger.error(f"Tray icon crashed: {e!r}")
            if self._stopping:
                break
            logger.warning("Tray icon stopped unexpectedly — rebuilding in 3s")
            time.sleep(3)
            try:
                self.icon = self._build_icon()
            except Exception as e:
                logger.error(f"Failed to rebuild tray icon: {e!r}")
                time.sleep(5)

    # ─────────────────────────────────────────────────────────
    #  Run
    # ─────────────────────────────────────────────────────────
    def run(self):
        # First run wizard
        if not run_if_needed():
            return

        cfg = config.load_config()
        logger.info("DriveBridge started.")

        self._apply_sync_mode()

        self.icon = self._build_icon()

        threading.Thread(target=self._status_loop,         daemon=True).start()
        threading.Thread(target=self._interval_sync_loop,  daemon=True).start()
        threading.Thread(target=self._watchdog_guard_loop, daemon=True).start()

        # Run the tray icon under a supervisor so it survives explorer restarts
        # and icon-thread crashes (see _run_icon_supervised).
        threading.Thread(target=self._run_icon_supervised, daemon=True).start()

        # Trigger an initial sweep to catch files edited while the app was offline
        if not self.rclone.is_paused:
            threading.Thread(target=self._on_sync_now, daemon=True).start()

        # Tkinter requires the exact Main Thread to stay stable long-term
        self.root.mainloop()


if __name__ == "__main__":
    import ctypes
    import sys

    # Enforce strict Single Instance Application using a native Windows OS-Level Mutex
    app_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "DriveBridge_Engine_Strict_Mutex")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(0, "DriveBridge is already running quietly in the background!\n\nPlease look for the DriveBridge cloud icon down in your Windows System Tray (bottom right taskbar).", "DriveBridge - Already Running", 0x30)
        sys.exit(0)

    app = DriveBridgeApp()
    app.run()

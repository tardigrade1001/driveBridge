"""Compact status dashboard opened from the DriveBridge tray icon."""
import datetime
import os
import tkinter as tk
from pathlib import PurePosixPath

import customtkinter as ctk

from core import config, logger, startup
from ui.theme import ACCENT

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG = "#11111b"
CARD = "#1e1e2e"
CARD_ALT = "#181825"
TEXT = "#cdd6f4"
MUTED = "#8f96ad"
GREEN = "#a6e3a1"
BLUE = "#89b4fa"
YELLOW = "#f9e2af"
RED = "#f38ba8"


class ActivityFeed:
    _is_open = False
    _instance = None

    @classmethod
    def open(cls, parent_root, rclone_manager):
        if cls._is_open:
            try:
                cls._instance.root.lift()
                cls._instance.root.focus_force()
                return
            except Exception:
                cls._is_open = False

        def create():
            cls._is_open = True
            cls._instance = cls(parent_root, rclone_manager)

        parent_root.after(0, create)

    def __init__(self, parent_root, rclone_manager):
        self.parent = parent_root
        self.rclone = rclone_manager
        self._last_history = None
        self._pulse = 0

        self.root = ctk.CTkToplevel(parent_root)
        self.root.title("DriveBridge")
        w = 470
        screen_h = self.root.winfo_screenheight()
        h = min(700, screen_h - 30)
        x = self.root.winfo_screenwidth() - w - 16
        y = max(10, screen_h - h - 48)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.resizable(False, False)
        self.root.configure(fg_color=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        from ui import gui_utils
        gui_utils.apply_window_icon(self.root)
        self._build()
        self._refresh()
        self._schedule_refresh()

    def _close(self):
        ActivityFeed._is_open = False
        ActivityFeed._instance = None
        try:
            self.root.destroy()
        except Exception:
            pass

    def _build(self):
        header = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        header.pack(fill="x", padx=18, pady=(16, 10))
        ctk.CTkLabel(header, text="DriveBridge",
                     font=ctk.CTkFont("Segoe UI", 23, "bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(header, text="×", width=30, height=30,
                      fg_color="transparent", hover_color="#313244",
                      font=ctk.CTkFont("Segoe UI", 20), command=self._close).pack(side="right")

        hero = ctk.CTkFrame(self.root, fg_color=CARD, corner_radius=14)
        hero.pack(fill="x", padx=16, pady=(0, 10))
        self._hero_dot = ctk.CTkLabel(hero, text="●", width=24,
                                      font=ctk.CTkFont(size=20))
        self._hero_dot.grid(row=0, column=0, rowspan=2, padx=(16, 6), pady=15)
        self._hero_title = ctk.CTkLabel(hero, text="Checking…", anchor="w",
                                        font=ctk.CTkFont("Segoe UI", 16, "bold"), text_color=TEXT)
        self._hero_title.grid(row=0, column=1, sticky="sw", pady=(12, 0))
        self._hero_subtitle = ctk.CTkLabel(hero, text="", anchor="w",
                                           font=ctk.CTkFont("Segoe UI", 13), text_color=MUTED)
        self._hero_subtitle.grid(row=1, column=1, sticky="nw", pady=(0, 12))
        hero.columnconfigure(1, weight=1)

        lanes = ctk.CTkFrame(self.root, fg_color="transparent")
        lanes.pack(fill="x", padx=16, pady=(0, 10))
        lanes.columnconfigure((0, 1), weight=1, uniform="lane")
        quick = ctk.CTkFrame(lanes, fg_color=CARD_ALT, corner_radius=12)
        quick.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ctk.CTkLabel(quick, text="QUICK UPLOADS", text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(anchor="w", padx=13, pady=(12, 3))
        self._quick_value = ctk.CTkLabel(quick, text="Ready", text_color=GREEN,
                                         font=ctk.CTkFont("Segoe UI", 16, "bold"), anchor="w")
        self._quick_value.pack(anchor="w", padx=13)
        self._quick_detail = ctk.CTkLabel(quick, text="Watching files", text_color=MUTED,
                                          font=ctk.CTkFont("Segoe UI", 12), anchor="w")
        self._quick_detail.pack(anchor="w", padx=13, pady=(2, 12))

        full = ctk.CTkFrame(lanes, fg_color=CARD_ALT, corner_radius=12)
        full.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(full, text="BACKGROUND CHECK", text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(anchor="w", padx=13, pady=(12, 3))
        self._full_value = ctk.CTkLabel(full, text="Idle", text_color=GREEN,
                                        font=ctk.CTkFont("Segoe UI", 16, "bold"), anchor="w")
        self._full_value.pack(anchor="w", padx=13)
        self._full_detail = ctk.CTkLabel(full, text="Safety reconciliation", text_color=MUTED,
                                         font=ctk.CTkFont("Segoe UI", 12), anchor="w")
        self._full_detail.pack(anchor="w", padx=13, pady=(2, 12))

        section = ctk.CTkFrame(self.root, fg_color="transparent")
        section.pack(fill="x", padx=18, pady=(2, 5))
        ctk.CTkLabel(section, text="Recent files", text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 16, "bold")).pack(side="left")
        self._last_sync_label = ctk.CTkLabel(section, text="", text_color=MUTED,
                                              font=ctk.CTkFont("Segoe UI", 12))
        self._last_sync_label.pack(side="right")

        self._feed = ctk.CTkScrollableFrame(self.root, fg_color=CARD_ALT,
                                             corner_radius=12, height=265)
        self._feed.pack(fill="both", expand=False, padx=16, pady=(0, 10))

        actions = ctk.CTkFrame(self.root, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 8))
        for col in range(3):
            actions.columnconfigure(col, weight=1)
        self._pause_btn = ctk.CTkButton(actions, text="Pause", height=34,
                                         fg_color="#313244", hover_color="#45475a",
                                         command=self._toggle_pause)
        self._pause_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(actions, text="Full check", height=34,
                      fg_color=ACCENT, hover_color="#9580ff",
                      command=self._sync_now).grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(actions, text="Open folder", height=34,
                      fg_color="#313244", hover_color="#45475a",
                      command=self._open_folder).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        footer = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        footer.pack(fill="x", padx=18, pady=(0, 12))
        self._startup_var = tk.BooleanVar(value=startup.is_registered())
        ctk.CTkCheckBox(footer, text="Start with Windows", variable=self._startup_var,
                        checkbox_width=18, checkbox_height=18, fg_color=ACCENT,
                        font=ctk.CTkFont("Segoe UI", 11),
                        command=self._toggle_startup).pack(side="left")
        ctk.CTkButton(footer, text="Settings", width=72, height=28,
                      fg_color="transparent", border_width=1, border_color="#45475a",
                      hover_color="#313244", command=self._open_settings).pack(side="right")
        ctk.CTkButton(footer, text="Log", width=48, height=28,
                      fg_color="transparent", hover_color="#313244",
                      command=self._open_log).pack(side="right", padx=4)

    def _refresh(self):
        paused = self.rclone.is_paused
        quick = getattr(self.rclone, "quick_upload_active", False)
        full = self.rclone.status == "syncing"
        pending = self.rclone.pending_upload_count()

        if paused:
            title, subtitle, color = "Sync paused", "No files will be transferred", RED
        elif self.rclone.last_error and self.rclone.status == "error":
            title, subtitle, color = "Needs attention", self.rclone.last_error, RED
        elif quick:
            title, subtitle, color = "Uploading now", self.rclone.quick_upload_file, BLUE
        elif pending:
            title, subtitle, color = "Files queued", f"{pending} waiting for quick upload", YELLOW
        else:
            title = "Watching for changes"
            subtitle = "New and modified files upload automatically"
            color = GREEN
        self._hero_dot.configure(text_color=color)
        self._hero_title.configure(text=title)
        self._hero_subtitle.configure(text=subtitle)
        self._pause_btn.configure(text="Resume" if paused else "Pause",
                                  fg_color=RED if paused else "#313244")

        if quick:
            dots = "." * (self._pulse % 4)
            self._quick_value.configure(text=f"Uploading{dots}", text_color=BLUE)
            self._quick_detail.configure(text=self._short(self.rclone.quick_upload_file, 27))
        elif pending:
            self._quick_value.configure(text=f"{pending} queued", text_color=YELLOW)
            self._quick_detail.configure(text="Waiting to upload")
        else:
            self._quick_value.configure(text="Ready", text_color=GREEN)
            self._quick_detail.configure(text="~4 sec after save")

        self._full_value.configure(text="Running" if full else "Idle",
                                   text_color=BLUE if full else GREEN)
        detail = self.rclone.live_progress if full and self.rclone.live_progress else "Safety reconciliation"
        self._full_detail.configure(text=self._short_front(detail, 29))

        entries = list(getattr(self.rclone, "recent_files", []))
        last = self.rclone.last_quick_synced or self.rclone.last_synced
        if not last and entries and entries[0].get("timestamp"):
            try:
                last = datetime.datetime.fromisoformat(entries[0]["timestamp"])
            except (TypeError, ValueError):
                pass
        self._last_sync_label.configure(text=self._relative_time(last))
        history = repr(entries)
        if history != self._last_history:
            self._last_history = history
            self._render_feed(entries)

    def _render_feed(self, entries):
        for widget in self._feed.winfo_children():
            widget.destroy()
        if not entries:
            ctk.CTkLabel(self._feed, text="No file activity in this session",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(pady=38)
            return
        for entry in entries[:7]:
            row = ctk.CTkFrame(self._feed, fg_color="transparent", height=54)
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)
            symbol = "✓" if entry["action"] != "Deleted" else "−"
            ctk.CTkLabel(row, text=symbol, width=24, text_color=GREEN if symbol == "✓" else RED,
                         font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
            path = PurePosixPath(str(entry["name"]).replace("\\", "/"))
            text_box = ctk.CTkFrame(row, fg_color="transparent")
            text_box.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(text_box, text=self._short(path.name, 39), anchor="w",
                         text_color=TEXT, font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(fill="x")
            parent = "" if str(path.parent) == "." else str(path.parent)
            meta = " · ".join(x for x in (self._format_size(entry.get("size")),
                                             self._format_duration(entry.get("duration")),
                                             self._short(parent, 30)) if x)
            ctk.CTkLabel(text_box, text=meta or entry.get("action", "Synced"), anchor="w",
                         text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11)).pack(fill="x")
            ctk.CTkLabel(row, text=entry["time"], width=42, text_color=MUTED,
                         font=ctk.CTkFont("Segoe UI", 11)).pack(side="right")

    @staticmethod
    def _short(text, length):
        text = str(text or "")
        return text if len(text) <= length else "…" + text[-(length - 1):]

    @staticmethod
    def _short_front(text, length):
        text = str(text or "")
        return text if len(text) <= length else text[:length - 1] + "…"

    @staticmethod
    def _relative_time(value):
        if not value:
            return "Nothing synced yet"
        seconds = max(0, int((datetime.datetime.now() - value).total_seconds()))
        if seconds < 60:
            return "Synced just now"
        if seconds < 3600:
            return f"Synced {seconds // 60}m ago"
        return f"Last sync {value.strftime('%H:%M')}"

    @staticmethod
    def _format_size(size):
        if size is None:
            return ""
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
            value /= 1024

    @staticmethod
    def _format_duration(duration):
        if duration is None:
            return ""
        return f"{duration:.1f}s" if duration < 10 else f"{duration:.0f}s"

    def _schedule_refresh(self):
        try:
            self._pulse += 1
            self._refresh()
            self.root.after(500, self._schedule_refresh)
        except Exception:
            pass

    def _toggle_pause(self):
        self.rclone.toggle_pause()

    def _sync_now(self):
        self.rclone.request_reconcile()

    def _open_folder(self):
        path = config.load_config().get("local_folder")
        if path and os.path.isdir(path):
            os.startfile(path)

    def _toggle_startup(self):
        startup.register() if self._startup_var.get() else startup.unregister()

    def _open_settings(self):
        from ui.settings_gui import SettingsWindow
        SettingsWindow.open(self.parent, self.rclone)

    def _open_log(self):
        if logger.LOG_FILE.exists():
            os.startfile(str(logger.LOG_FILE))

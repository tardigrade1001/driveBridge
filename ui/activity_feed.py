"""
DriveBridge activity feed window.
Opens on single tray click — shows recent sync events.
"""
import tkinter as tk
import customtkinter as ctk
from core import logger
from core import startup
from ui.theme import ACCENT, LEVEL_COLORS

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG      = "#1e1e2e"
SURFACE = "#2a2a3e"


class ActivityFeed:
    _is_open = False
    _instance = None

    @classmethod
    def open(cls, parent_root, rclone_manager):
        """Open or bring to front — runs on central UI thread."""
        if cls._is_open:
            try:
                if cls._instance and cls._instance.root.winfo_exists():
                    cls._instance.root.lift()
                    return
            except Exception:
                pass
            cls._is_open = False  # Reset if destroyed

        def _create():
            cls._is_open = True
            cls._instance = cls(parent_root, rclone_manager)
            def on_close():
                ActivityFeed._is_open = False
                try: cls._instance.root.destroy()
                except Exception: pass
            cls._instance.root.protocol("WM_DELETE_WINDOW", on_close)

        # Safely inject into the master Tk loop
        parent_root.after(0, _create)

    def __init__(self, parent_root, rclone_manager):
        self.rclone = rclone_manager
        self.parent = parent_root

        self.root = ctk.CTkToplevel(parent_root)
        self.root.title("DriveBridge Activity")

        # Calculate screen geometry to pin it to the bottom right above the taskbar
        w, h = 360, 320
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        x = ws - w - 20  # 20px padding from right
        y = hs - h - 60  # 60px padding from bottom (rough taskbar size)

        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.resizable(False, False)

        # Make it behave like a Dropbox popup
        self.root.overrideredirect(True)      # Strips the Windows title bar and close buttons
        self.root.attributes("-topmost", True) # Keep it visibly hovering
        self.root.focus_force()               # Force focus so click-away works

        # Destroy the panel instantly if the user clicks anywhere else on their screen
        def on_focus_out(event):
            # Only trigger if the focus actually left our application completely
            if not str(self.root.focus_get()).startswith(str(self.root)):
                try:
                    ActivityFeed._is_open = False
                    self.root.destroy()
                except Exception: pass

        self.root.bind("<FocusOut>", on_focus_out)

        from ui import gui_utils
        gui_utils.apply_window_icon(self.root)

        self._build()
        self._refresh()
        self._schedule_refresh()

    def _build(self):
        # Header row
        header = ctk.CTkFrame(self.root, fg_color=SURFACE, corner_radius=0, height=48)
        header.pack(fill="x")
        header.pack_propagate(False)

        self._status_dot = ctk.CTkLabel(header, text="●", text_color="#888888",
                                         font=ctk.CTkFont("Segoe UI", size=16, weight="bold"))
        self._status_dot.pack(side="left", padx=(12,4), pady=12)

        self._status_label = ctk.CTkLabel(header, text="idle",
                                           font=ctk.CTkFont("Segoe UI", size=14, weight="bold"))
        self._status_label.pack(side="left", pady=12)

        self._pause_btn = ctk.CTkButton(header, text="Pause", width=65, height=28,
                      fg_color="#313244", hover_color="#45475a",
                      font=ctk.CTkFont("Segoe UI", size=13),
                      command=self._toggle_pause)
        self._pause_btn.pack(side="right", padx=(4, 8), pady=10)

        ctk.CTkButton(header, text="Sync Now", width=85, height=28,
                      fg_color=ACCENT, hover_color="#9580ff",
                      font=ctk.CTkFont("Segoe UI", size=13, weight="bold"),
                      command=self._sync_now
                      ).pack(side="right", padx=(8, 4), pady=10)

        self.header_frame = header # saved for positional inserting

        # Progress tracking (Hidden by default)
        self._progress_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self._progress_label = ctk.CTkLabel(self._progress_frame, text="",
                                            text_color="#cdd6f4", font=ctk.CTkFont("Segoe UI", size=12), anchor="w", justify="left", wraplength=330)
        self._progress_label.pack(side="left", fill="x", expand=True)

        # Activity list
        ctk.CTkLabel(self.root, text="Recent activity",
                     font=ctk.CTkFont("Segoe UI", size=14, weight="bold"), text_color="#a6adc8"
                     ).pack(anchor="w", padx=12, pady=(10, 2))

        self._feed_scroll = ctk.CTkScrollableFrame(self.root, fg_color="#181825", orientation="horizontal")
        self._feed_scroll.pack(fill="both", expand=True, padx=8, pady=4)

        self._feed_label = ctk.CTkLabel(self._feed_scroll, text="", justify="left", font=ctk.CTkFont("Consolas", size=11), text_color="#cdd6f4", anchor="nw")
        self._feed_label.pack(fill="both", expand=True, padx=4, pady=4)

        # Footer
        footer = ctk.CTkFrame(self.root, fg_color=SURFACE, corner_radius=0, height=40)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self._startup_var = tk.BooleanVar(value=startup.is_registered())
        ctk.CTkCheckBox(footer, text="Start with Windows",
                        variable=self._startup_var,
                        fg_color=ACCENT, hover_color="#9580ff",
                        font=ctk.CTkFont("Segoe UI", size=12),
                        command=self._toggle_startup
                        ).pack(side="left", padx=10, pady=8)

        ctk.CTkButton(footer, text="Settings", width=70, height=26,
                      fg_color="#45475a", hover_color="#585b70",
                      font=ctk.CTkFont("Segoe UI", size=12),
                      command=self._open_settings
                      ).pack(side="right", padx=(4, 8), pady=7)

        ctk.CTkButton(footer, text="View Full Log", width=100, height=26,
                      fg_color="#45475a", hover_color="#585b70",
                      font=ctk.CTkFont("Segoe UI", size=12),
                      command=self._open_log
                      ).pack(side="right", padx=(8, 4), pady=7)

    def _toggle_pause(self):
        self.rclone.toggle_pause()

    def _refresh(self):
        # Update status
        status = self.rclone.status
        if self.rclone.is_paused:
            status = "paused"
            self._pause_btn.configure(text="Resume", fg_color="#f38ba8", hover_color="#f9e2af")
        else:
            self._pause_btn.configure(text="Pause", fg_color="#313244", hover_color="#45475a")

        color  = {
            "idle":     "#a6adc8",
            "paused":   "#f38ba8",
            "syncing":  "#89b4fa",
            "error":    "#f38ba8",
        }.get(status, "#a6adc8")
        self._status_dot.configure(text_color=color)
        self._status_label.configure(text=status)

        # Handle Live Progress
        if status == "syncing" and getattr(self.rclone, "live_progress", ""):
            text = self.rclone.live_progress
            self._progress_label.configure(text=text)
            if not self._progress_frame.winfo_ismapped():
                self._progress_frame.pack(fill="x", padx=14, pady=(2, 6), after=self.header_frame)
        else:
            if self._progress_frame.winfo_ismapped():
                self._progress_frame.pack_forget()

        # Rebuild feed efficiently by checking for actual cache state changes
        entries = getattr(self.rclone, "recent_files", [])
        current_history = repr(entries)

        if not hasattr(self, "_last_history") or self._last_history != current_history:
            self._last_history = current_history

            if not entries:
                self._feed_label.configure(text="No recently synced files yet.")
            else:
                lines = []
                for e in entries:
                    action_char = "[-]" if e["action"] == "Deleted" else "[+]"
                    lines.append(f"{action_char} {e['time']} | {e['name']}")
                self._feed_label.configure(text="\n".join(lines))

    def _schedule_refresh(self):
        try:
            self._refresh()
        except Exception as e:
            logger.error(f"ActivityFeed refresh error: {e}")
        paused = self.rclone.is_paused
        syncing = self.rclone.status == "syncing" and not paused
        delay = 500 if syncing else 3000
        try:
            self.root.after(delay, self._schedule_refresh)
        except Exception:
            pass  # window was destroyed, loop ends naturally

    def _sync_now(self):
        self.rclone.full_bisync()

    def _toggle_startup(self):
        if self._startup_var.get():
            startup.register()
        else:
            startup.unregister()

    def _open_settings(self):
        from ui.settings_gui import SettingsWindow
        SettingsWindow.open(self.parent, self.rclone)

    def _open_log(self):
        import os
        log_path = logger.LOG_FILE
        if log_path.exists():
            os.startfile(str(log_path))

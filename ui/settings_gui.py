"""
Settings window for DriveBridge — customtkinter version.
pip install customtkinter
"""
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from core import config
from core import logger
from core import startup
from ui.theme import ACCENT, LEVEL_COLORS

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class SettingsWindow:
    _is_open = False
    _instance = None

    @classmethod
    def open(cls, parent_root, rclone_manager, on_close_callback=None):
        if cls._is_open:
            if cls._instance and cls._instance.root.winfo_exists():
                cls._instance.root.lift()
            return

        def _create():
            cls._is_open = True
            cls._instance = cls(rclone_manager, parent_root)
            def on_close():
                cls._is_open = False
                cls._instance.root.destroy()
                if on_close_callback:
                    on_close_callback()
            cls._instance.root.protocol("WM_DELETE_WINDOW", on_close)

        parent_root.after(0, _create)

    def __init__(self, rclone_manager, parent):
        self.rclone = rclone_manager
        self.cfg    = config.load_config()

        self.root = ctk.CTkToplevel(parent)
        self.root.title("DriveBridge Settings")
        self.root.geometry("480x460")
        self.root.resizable(False, False)

        from ui import gui_utils
        gui_utils.apply_window_icon(self.root)

        self._build_ui()

    def _build_ui(self):
        container = ctk.CTkScrollableFrame(self.root, width=460, height=390)
        container.pack(padx=10, pady=10, fill="both", expand=True)

        self._add_section(container, "General", self._build_general)
        self._add_section(container, "Folders", self._build_pc)
        self._add_section(container, "Sync Behavior", self._build_sync)
        self._add_section(container, "Logs", self._build_log)

        ctk.CTkButton(self.root, text="Close", width=80,
                      fg_color="#45475a", hover_color="#585b70",
                      command=self.root.destroy
                      ).pack(side="right", padx=12, pady=6)

    def _add_section(self, parent, title, builder):
        ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT).pack(anchor="w", pady=(10, 5), padx=5)
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=5)
        builder(f)

    # ─────────────────────────────────────────────────────────
    #  Tabs
    # ─────────────────────────────────────────────────────────
    def _build_general(self, tab):
        self._row(tab, "rclone path",  0, self._file_pick(tab, "rclone_path"))
        self._row(tab, "Remote name",  1, self._ent(tab, "remote_name"))
        self._row(tab, "Drive folder", 2, self._ent(tab, "drive_folder"))
        self._row(tab, "Custom Icon",  3, self._file_pick(tab, "custom_icon_path"))

        # Startup toggle
        self._startup_var = tk.BooleanVar(value=startup.is_registered())
        ctk.CTkCheckBox(tab, text="Launch at Windows startup",
                        variable=self._startup_var,
                        fg_color=ACCENT, hover_color="#9580ff",
                        command=self._toggle_startup
                        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=10)

    def _build_sync(self, tab):
        ctk.CTkLabel(tab, text="Sync trigger", anchor="w").grid(
            row=0, column=0, sticky="w", padx=8, pady=6)

        self._sync_mode_var = tk.StringVar(value=self.cfg.get("sync_mode", "interval"))
        sf = ctk.CTkFrame(tab, fg_color="transparent")
        sf.grid(row=0, column=1, sticky="w", pady=6)
        for i, val in enumerate(("interval", "watchdog", "both")):
            ctk.CTkRadioButton(sf, text=val.capitalize(),
                               variable=self._sync_mode_var, value=val,
                               fg_color=ACCENT, hover_color="#9580ff",
                               command=self._on_sync_mode_change
                               ).grid(row=0, column=i, padx=6)

        self._interval_label = ctk.CTkLabel(tab, text="Interval (min)", anchor="w")
        self._interval_entry = self._ent(tab, "sync_interval_minutes")
        self._interval_label.grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self._interval_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=4)

        self._confirm_var = tk.BooleanVar(value=self.cfg.get("confirm_deletions", True))
        ctk.CTkCheckBox(tab, text="Confirm before syncing deletions",
                        variable=self._confirm_var,
                        fg_color=ACCENT, hover_color="#9580ff",
                        command=lambda: self._set("confirm_deletions", self._confirm_var.get())
                        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=8)

        self._on_sync_mode_change()


    def _build_pc(self, tab):
        self._row(tab, "Local folder", 0, self._dir_pick(tab, "local_folder"))

        # Last synced info
        last = self.rclone.last_synced
        last_str = last.strftime("%Y-%m-%d %H:%M:%S") if last else "Never"
        ctk.CTkLabel(tab, text="Last synced", anchor="w").grid(
            row=1, column=0, sticky="w", padx=8, pady=8)
        ctk.CTkLabel(tab, text=last_str, text_color="#888888", anchor="w").grid(
            row=1, column=1, sticky="w", padx=8, pady=8)


    def _build_log(self, tab):
        bf = ctk.CTkFrame(tab, fg_color="transparent")
        bf.pack(fill="x", padx=4, pady=4)
        ctk.CTkButton(bf, text="Open log file", width=100, fg_color="#45475a",
                      hover_color="#585b70", command=self._open_log_file).pack(side="left", padx=2)
        ctk.CTkButton(bf, text="Refresh", width=80, fg_color="#45475a",
                      hover_color="#585b70", command=self._refresh_log).pack(side="left", padx=2)

        self._log_frame = ctk.CTkScrollableFrame(tab, height=150)
        self._log_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self._refresh_log()

    def _refresh_log(self):
        for w in self._log_frame.winfo_children():
            w.destroy()
        entries = logger.get_entries(60)
        if not entries:
            ctk.CTkLabel(self._log_frame, text="No log entries yet.",
                         text_color="#555555").pack(pady=10)
            return
        for e in entries:
            color = LEVEL_COLORS.get(e["level"], "#aaaaaa")
            row = ctk.CTkFrame(self._log_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=e["time"][11:], text_color="#555555",
                         font=ctk.CTkFont(size=10), width=55, anchor="w"
                         ).pack(side="left")
            ctk.CTkLabel(row, text=f"[{e['level']}]", text_color=color,
                         font=ctk.CTkFont(size=10), width=45, anchor="w"
                         ).pack(side="left")
            ctk.CTkLabel(row, text=e["message"], text_color="#cccccc",
                         font=ctk.CTkFont(size=10), anchor="w", wraplength=250
                         ).pack(side="left", fill="x")

    def _open_log_file(self):
        import os
        log_path = logger.LOG_FILE
        if log_path.exists():
            os.startfile(str(log_path))


    # ─────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────
    def _on_sync_mode_change(self, *_):
        mode = self._sync_mode_var.get()
        self._set("sync_mode", mode)
        if mode in ("interval", "both"):
            self._interval_label.grid()
            self._interval_entry.grid()
        else:
            self._interval_label.grid_remove()
            self._interval_entry.grid_remove()

    def _toggle_startup(self):
        if self._startup_var.get():
            startup.register()
        else:
            startup.unregister()

    def _row(self, parent, label, row, widget):
        ctk.CTkLabel(parent, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", padx=8, pady=5)
        widget.grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        parent.columnconfigure(1, weight=1)

    def _ent(self, parent, key):
        var = tk.StringVar(parent)
        e   = ctk.CTkEntry(parent, textvariable=var)
        var.set(str(self.cfg.get(key, "")))
        var.trace_add("write", lambda *_: self._set(key, var.get()))
        e._var = var  # Keep reference alive!
        return e

    def _dd(self, parent, key, values):
        var = tk.StringVar(parent, value=str(self.cfg.get(key, values[0])))
        dd  = ctk.CTkOptionMenu(parent, variable=var, values=values,
                                fg_color="#313244", button_color=ACCENT,
                                button_hover_color="#9580ff")
        var.trace_add("write", lambda *_: self._set(key, var.get()))
        dd._var = var
        return dd

    def _dir_pick(self, parent, key):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.columnconfigure(0, weight=1)
        var = tk.StringVar(f)
        ctk.CTkEntry(f, textvariable=var).grid(row=0, column=0, sticky="ew")
        var.set(str(self.cfg.get(key, "")))
        var.trace_add("write", lambda *_: self._set(key, var.get()))
        ctk.CTkButton(f, text="…", width=28, fg_color="#45475a",
                      hover_color="#585b70",
                      command=lambda: var.set(filedialog.askdirectory() or var.get())
                      ).grid(row=0, column=1, padx=2)
        f._var = var
        return f

    def _file_pick(self, parent, key):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.columnconfigure(0, weight=1)
        var = tk.StringVar(f)
        ctk.CTkEntry(f, textvariable=var).grid(row=0, column=0, sticky="ew")
        var.set(str(self.cfg.get(key, "")))
        var.trace_add("write", lambda *_: self._set(key, var.get()))
        ctk.CTkButton(f, text="…", width=28, fg_color="#45475a",
                      hover_color="#585b70",
                      command=lambda: var.set(filedialog.askopenfilename() or var.get())
                      ).grid(row=0, column=1, padx=2)
        f._var = var
        return f

    def _set(self, key, value):
        self.cfg[key] = value
        config.set_value(key, value)

"""
DriveBridge first-run wizard.
Shows on first launch when config doesn't exist yet.
"""
import subprocess
import webbrowser
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
from core import config
from core import startup
from ui.theme import ACCENT

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

RCLONE_DOWNLOAD_URL = "https://rclone.org/downloads/"
RCLONE_GUIDE_URL    = "https://rclone.org/drive/"


# ─────────────────────────────────────────────────────────
#  rclone helpers
# ─────────────────────────────────────────────────────────

def _rclone_exe() -> str:
    return config.load_config().get("rclone_path", "rclone") or "rclone"


def _remote_name() -> str:
    return config.load_config().get("remote_name", "gdrive") or "gdrive"


def _check_rclone() -> tuple[bool, bool]:
    """Returns (rclone_installed, target_remote_exists)."""
    exe = _rclone_exe()
    try:
        result = subprocess.run(
            [exe, "listremotes"],
            capture_output=True, text=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        remotes = [r.rstrip(":").lower() for r in result.stdout.strip().splitlines()]
        return True, _remote_name().lower() in remotes
    except FileNotFoundError:
        return False, False
    except Exception:
        return True, False


def _launch_rclone_config():
    exe = _rclone_exe()
    subprocess.Popen(f'start cmd /k "{exe}" config', shell=True)


# ─────────────────────────────────────────────────────────
#  Wizard
# ─────────────────────────────────────────────────────────

class SetupWizard:
    def __init__(self):
        self.completed = False
        self._poll_job = None   # tracks the active after() polling job

        self.root = ctk.CTk()
        self.root.title("DriveBridge Setup")
        self.root.geometry("460x520")
        self.root.resizable(False, False)

        from ui import gui_utils
        gui_utils.apply_window_icon(self.root)

        self._step = 0
        self._build()
        self.root.mainloop()

    def _build(self):
        header = ctk.CTkFrame(self.root, fg_color="#1a1a2e", corner_radius=0, height=70)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="☁  DriveBridge Setup",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=18)

        self._container = ctk.CTkFrame(self.root, fg_color="transparent")
        self._container.pack(fill="both", expand=True, padx=20, pady=10)

        nav = ctk.CTkFrame(self.root, fg_color="transparent")
        nav.pack(fill="x", padx=20, pady=10)
        self._back_btn = ctk.CTkButton(nav, text="Back", width=80,
                                       fg_color="#45475a", hover_color="#585b70",
                                       command=self._back)
        self._back_btn.pack(side="left")
        self._next_btn = ctk.CTkButton(nav, text="Next →", width=80,
                                       fg_color=ACCENT, hover_color="#9580ff",
                                       command=self._next)
        self._next_btn.pack(side="right")

        self._steps = [
            self._step_welcome,
            self._step_rclone,
            self._step_paths,
            self._step_startup,
            self._step_done,
        ]
        self._show_step(0)

    def _show_step(self, n):
        self._cancel_poll()
        for w in self._container.winfo_children():
            w.destroy()
        self._step = n
        self._steps[n]()
        self._back_btn.configure(state="normal" if n > 0 else "disabled")
        self._next_btn.configure(text="Finish" if n == len(self._steps) - 1 else "Next →")

    def _next(self):
        if not self._validate():
            return
        if self._step == len(self._steps) - 1:
            self.completed = True
            self.root.destroy()
        else:
            self._show_step(self._step + 1)

    def _back(self):
        if self._step > 0:
            self._show_step(self._step - 1)

    def _validate(self) -> bool:
        """Step-specific validation before advancing. Returns False and shows error if invalid."""
        if self._step == 2:  # paths step
            local = config.load_config().get("local_folder", "").strip()
            if not local:
                self._show_path_error("Please choose a local folder before continuing.")
                return False
            drive = config.load_config().get("drive_folder", "").strip()
            if not drive:
                self._show_path_error("Please enter a Drive folder name before continuing.")
                return False
        return True

    def _show_path_error(self, msg: str):
        if hasattr(self, "_path_error_label"):
            self._path_error_label.configure(text=msg)
        else:
            self._path_error_label = ctk.CTkLabel(
                self._container, text=msg, text_color="#e05050",
                font=ctk.CTkFont(size=11), wraplength=380)
            self._path_error_label.pack(pady=(6, 0))

    # ─────────────────────────────────────────────────────────
    #  Steps
    # ─────────────────────────────────────────────────────────

    def _step_welcome(self):
        ctk.CTkLabel(self._container,
                     text="Welcome to DriveBridge",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=20)
        ctk.CTkLabel(self._container,
                     text="This wizard will walk you through connecting\n"
                          "your Google Drive and choosing which folder to sync.\n\n"
                          "It should only take a minute.",
                     justify="center").pack(pady=10)

    # ── rclone step ──────────────────────────────────────────

    def _step_rclone(self):
        remote = _remote_name()

        ctk.CTkLabel(self._container, text="Google Drive Connection",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(16, 4))
        ctk.CTkLabel(self._container,
                     text="DriveBridge uses rclone to sync with Google Drive.\nLet's make sure everything is set up.",
                     text_color="#888888", justify="center").pack(pady=(0, 12))

        # Status dots
        status_frame = ctk.CTkFrame(self._container, fg_color="#1e1e2e", corner_radius=8)
        status_frame.pack(fill="x", pady=(0, 12))
        self._rclone_dot = self._status_row(status_frame, "rclone installed")
        self._remote_dot = self._status_row(status_frame, f"'{remote}' remote configured")

        # Action buttons — reconfigured dynamically after first check
        self._btn_frame = ctk.CTkFrame(self._container, fg_color="transparent")
        self._btn_frame.pack(fill="x")

        self._config_btn = ctk.CTkButton(self._btn_frame, text="Run rclone config", width=160,
                                         fg_color=ACCENT, hover_color="#9580ff",
                                         command=self._on_run_rclone_config)
        self._config_btn.pack(side="left")

        self._download_btn = ctk.CTkButton(self._btn_frame, text="Download rclone", width=150,
                                           fg_color="#313244", hover_color="#45475a",
                                           command=lambda: webbrowser.open(RCLONE_DOWNLOAD_URL))
        # shown only when rclone is missing — packed dynamically

        ctk.CTkButton(self._btn_frame, text="Recheck", width=80,
                      fg_color="#45475a", hover_color="#585b70",
                      command=self._run_rclone_check
                      ).pack(side="left", padx=(8, 0))

        # Guide link
        self._guide_frame = ctk.CTkFrame(self._container, fg_color="transparent")
        self._guide_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkLabel(self._container,
                     text="Already configured? Hit Recheck, then Next →",
                     text_color="#555555", font=ctk.CTkFont(size=11)).pack(pady=(8, 0))

        self._run_rclone_check()

    def _status_row(self, parent, label: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=5)
        dot = ctk.CTkLabel(row, text="●", text_color="#555555",
                           font=ctk.CTkFont(size=13), width=20)
        dot.pack(side="left")
        ctk.CTkLabel(row, text=label, anchor="w").pack(side="left", padx=6)
        return dot

    def _run_rclone_check(self):
        rclone_ok, remote_ok = _check_rclone()

        self._rclone_dot.configure(text_color="#40a840" if rclone_ok else "#e05050")
        self._remote_dot.configure(text_color="#40a840" if remote_ok else
                                   ("#555555" if not rclone_ok else "#e05050"))

        if not rclone_ok:
            # Show download button, disable config button, show install guide
            self._config_btn.configure(state="disabled", fg_color="#313244")
            self._download_btn.pack(side="left", padx=(8, 0))
            for w in self._guide_frame.winfo_children():
                w.destroy()
            ctk.CTkLabel(self._guide_frame,
                         text="rclone not found. Download it, install it, then hit Recheck.",
                         text_color="#f0a500", font=ctk.CTkFont(size=11), wraplength=400
                         ).pack(anchor="w")
            ctk.CTkButton(self._guide_frame, text="Google Drive setup guide →",
                          fg_color="transparent", hover_color="#2a2a3e",
                          text_color=ACCENT, font=ctk.CTkFont(size=11, underline=True),
                          anchor="w", width=0, height=20,
                          command=lambda: webbrowser.open(RCLONE_GUIDE_URL)
                          ).pack(anchor="w")
        else:
            self._config_btn.configure(state="normal", fg_color=ACCENT)
            self._download_btn.pack_forget()
            for w in self._guide_frame.winfo_children():
                w.destroy()

        return remote_ok

    def _on_run_rclone_config(self):
        _launch_rclone_config()
        self._start_poll(max_attempts=24, interval_ms=5000)  # poll every 5s for 2 min

    def _start_poll(self, max_attempts: int, interval_ms: int, attempt: int = 0):
        self._cancel_poll()
        if attempt >= max_attempts:
            return
        done = self._run_rclone_check()
        if done:
            return
        self._poll_job = self.root.after(
            interval_ms,
            lambda: self._start_poll(max_attempts, interval_ms, attempt + 1)
        )

    def _cancel_poll(self):
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

    # ── paths step ───────────────────────────────────────────

    def _step_paths(self):
        ctk.CTkLabel(self._container, text="Set your folders",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=12)

        cfg = config.load_config()
        self._path_row("Local folder", "local_folder", cfg)
        self._drive_row(cfg)

    def _path_row(self, label, key, cfg):
        ctk.CTkLabel(self._container, text=label, anchor="w").pack(fill="x", pady=(8, 2))
        f = ctk.CTkFrame(self._container, fg_color="transparent")
        f.pack(fill="x")
        f.columnconfigure(0, weight=1)
        var = tk.StringVar(value=str(cfg.get(key, "")))
        ctk.CTkEntry(f, textvariable=var).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        var.trace_add("write", lambda *_: config.set_value(key, var.get()))
        ctk.CTkButton(f, text="…", width=30, fg_color="#45475a",
                      command=lambda: var.set(filedialog.askdirectory() or var.get())
                      ).grid(row=0, column=1)

    def _drive_row(self, cfg):
        ctk.CTkLabel(self._container, text="Drive folder name", anchor="w").pack(fill="x", pady=(12, 2))
        var = tk.StringVar(value=str(cfg.get("drive_folder", "")))
        ctk.CTkEntry(self._container, textvariable=var, placeholder_text="e.g. Projects").pack(fill="x")
        ctk.CTkLabel(self._container,
                     text="The folder name inside your Google Drive root.",
                     text_color="#888888").pack(anchor="w", pady=2)
        var.trace_add("write", lambda *_: config.set_value("drive_folder", var.get()))

    # ── startup step ─────────────────────────────────────────

    def _step_startup(self):
        ctk.CTkLabel(self._container, text="Start with Windows?",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=20)

        self._startup_var = tk.BooleanVar(value=startup.is_registered())
        ctk.CTkCheckBox(self._container,
                        text="Launch DriveBridge automatically on login",
                        variable=self._startup_var,
                        fg_color=ACCENT, hover_color="#9580ff"
                        ).pack(pady=10)
        ctk.CTkLabel(self._container,
                     text="You can change this later in Settings.",
                     text_color="#888888").pack()

        def apply(*_):
            if self._startup_var.get():
                startup.register()
            else:
                startup.unregister()

        self._startup_var.trace_add("write", apply)

    # ── done step ────────────────────────────────────────────

    def _step_done(self):
        ctk.CTkLabel(self._container, text="✓  All set!",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="#40a840").pack(pady=30)
        ctk.CTkLabel(self._container,
                     text="DriveBridge is ready.\n\n"
                          "Click Finish to start — you'll see\n"
                          "the icon appear in your system tray.",
                     justify="center").pack()


def run_if_needed():
    """Run the wizard if this is a first launch (no config file exists)."""
    from pathlib import Path
    cfg_file = Path(__file__).parent.parent / "drivebridge_config.json"
    if not cfg_file.exists():
        wiz = SetupWizard()
        return wiz.completed
    return True

import tkinter as tk
import customtkinter as ctk
import os
import shutil
import threading
from pathlib import Path

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT   = "#f0a500" # Orange for warning
BG       = "#1e1e2e"
SURFACE  = "#2a2a3e"

class ConflictResolver:
    _is_open = False

    @classmethod
    def open(cls, parent_root, rclone_manager, local_path, conflict_files):
        if cls._is_open:
            return

        def _create():
            cls._is_open = True
            instance = cls(parent_root, rclone_manager, local_path, conflict_files)
            def on_close():
                cls._is_open = False
                instance.root.destroy()
            instance.root.protocol("WM_DELETE_WINDOW", on_close)

        parent_root.after(0, _create)

    def __init__(self, parent_root, rclone, local_path, conflict_files):
        self.rclone = rclone
        self.local_path = local_path
        self.conflicts = conflict_files

        self.root = ctk.CTkToplevel(parent_root)
        self.root.title("DriveBridge - Sync Conflicts Detected")
        self.root.geometry("600x400")
        self.root.attributes("-topmost", True)

        from ui import gui_utils
        gui_utils.apply_window_icon(self.root)

        ctk.CTkLabel(self.root, text="Conflicts Detected!", font=ctk.CTkFont(size=18, weight="bold"), text_color=ACCENT).pack(pady=(15, 5))
        ctk.CTkLabel(self.root, text="rclone found files modified simultaneously on both devices.\nPlease choose which version to keep.", text_color="#aaaaaa").pack(pady=5)

        self._frame = ctk.CTkScrollableFrame(self.root, fg_color="transparent")
        self._frame.pack(fill="both", expand=True, padx=15, pady=10)

        self._build_list()

    def _build_list(self):
        for w in self._frame.winfo_children():
            w.destroy()

        if not self.conflicts:
            ctk.CTkLabel(self._frame, text="All conflicts resolved!", text_color="#40a840").pack(pady=20)
            ctk.CTkButton(self.root, text="Close", command=self.root.destroy, fg_color="#45475a").pack(pady=10)
            return

        for idx, f in enumerate(self.conflicts):
            row = ctk.CTkFrame(self._frame, fg_color=SURFACE, corner_radius=6)
            row.pack(fill="x", pady=5)

            c_name = f.name
            ctk.CTkLabel(row, text=c_name, font=ctk.CTkFont(size=12), anchor="w").pack(side="left", padx=10, pady=10, fill="x", expand=True)

            ctk.CTkButton(row, text="Keep This", width=80, fg_color=ACCENT, hover_color="#d69000",
                          command=lambda f=f: self._resolve(f, keep="this")).pack(side="right", padx=(5, 10))

            ctk.CTkButton(row, text="Open Folder", width=80, fg_color="#45475a", hover_color="#585b70",
                          command=lambda f=f: self._open_dir(f)).pack(side="right", padx=5)

    def _open_dir(self, file_path):
        os.startfile(str(file_path.parent))

    def _resolve(self, file_path, keep):
        # rclone names them filename..path1..conflict or filename..path2..conflict
        # If they pick "Keep This", we rename it back to the base filename and delete the other conflict if it exists
        try:
            base_name = file_path.name.split("..")[0]
            if not base_name: base_name = file_path.name

            final_path = file_path.parent / base_name

            # Remove the existing base file if it exists
            if final_path.exists():
                final_path.unlink()

            file_path.rename(final_path)

            # Re-scan conflicts
            self.conflicts.remove(file_path)
            self._build_list()
        except Exception as e:
            import tkinter.messagebox
            tkinter.messagebox.showerror("Error", f"Failed to resolve: {str(e)}")

def open_resolver(parent_root, rclone_manager, local_path, conflicts):
    ConflictResolver.open(parent_root, rclone_manager, local_path, conflicts)

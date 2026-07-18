# ☁️ DriveBridge

**A lightweight Google Drive sync client for Windows. Lives in your system tray, stays out of your way.**

DriveBridge wraps [`rclone bisync`](https://rclone.org/bisync/) in a polished Dropbox-style tray app. Two-way sync, live file watching, conflict resolution, and mass-deletion protection, without the bloat of the official client.

> **Windows only.** Requires Python 3.10+ and rclone.

---

## Features

- **Two-way bisync**: keeps a local folder and a Google Drive folder in sync, both ways
- **Quick uploads**: new and modified local files upload individually within seconds instead of waiting for a full-folder scan
- **Live watchdog**: detects file changes instantly, debounces repeated saves per file, and keeps batches of changed files queued separately
- **Two-lane sync engine**: separates quick uploads from slower full two-way reconciliation
- **Reconciliation safeguards**: pauses quick-upload event handling during full scans so metadata updates cannot create upload loops
- **Idle-aware startup**: gives new local files priority, then starts the boot-time reconciliation after 15 seconds without local activity
- **Persistent activity dashboard**: shows quick uploads, background checks, queue state, recent files, sizes, durations, and last-sync time across restarts
- **Optimized full scanning**: parallel checkers and checksum-skipping reduce reconciliation overhead
- **Automatic Conflict Resolution**: uses "newer wins" logic to resolve simultaneous edits instantly, preventing "conflict file" clutter while preserving your latest save
- **Cross-Platform Stability**: handles Google Drive's 1-second timestamp rounding to prevent "false" change detections and unnecessary syncs
- **Mass deletion protection**: if a sync would delete a large number of files on Drive, it pauses and asks for confirmation before touching anything
- **Boot-sweep recovery**: runs a full reconciliation on every launch to catch changes made while the app was offline
- **Smart exclusions**: ignores Windows and Office lock files (`~$*`, `Thumbs.db`, `.tmp`, `desktop.ini`) that would otherwise cause endless sync loops
- **Single-instance enforcement**: native Windows mutex prevents duplicate background processes
- **Native toast notifications**: sync complete and error alerts via the Windows notification center, no extra packages required
- **Catppuccin dark theme**

---

## Requirements

- **Python 3.10+**: [python.org](https://www.python.org/downloads/)
- **rclone**: [rclone.org/downloads](https://rclone.org/downloads/)

---

## Installation

**1. Clone the repo**
```cmd
git clone https://github.com/your-username/DriveBridge.git
cd DriveBridge
```

**2. Install Python dependencies**
```cmd
pip install -r requirements.txt
```

**3. Install rclone**

Download from [rclone.org/downloads](https://rclone.org/downloads/) and install it. The setup wizard will help you locate the executable on first launch.

**4. Launch DriveBridge**
```cmd
Launch DriveBridge.bat
```

On first launch, the setup wizard will walk you through authenticating with Google Drive and choosing your sync folder. No manual rclone configuration is needed.

---

## Usage

Double-click `Launch DriveBridge.bat` to start. DriveBridge runs silently in the system tray.

| Tray action | What it does |
|---|---|
| Single click | Open the sync dashboard (quick uploads, background check, queue, and recent files) |
| Double click | Open Settings |
| Right click > Sync Now | Trigger an immediate sync |
| Right click > Pause | Pause all sync activity |
| Right click > Quit | Exit cleanly, terminating all rclone processes |

### Sync modes

Configure in **Settings > Sync Behavior**:

| Mode | Description |
|---|---|
| **Interval** | Syncs every N minutes (default: 30) |
| **Watchdog** | Syncs within seconds of any file change |
| **Both** | Watchdog for instant sync, with interval as a safety net |

### How fast sync works

DriveBridge uses two independent sync paths:

- Creating or modifying a local file schedules a checksum-aware direct `rclone copyto` after a four-second debounce. Repeated saves reset only that file's timer, and multiple files remain separate queue entries.
- Deletions, renames, remote changes, startup recovery, and periodic safety checks use the full `rclone bisync` reconciliation path.

Quick uploads pause while a full reconciliation is scanning the folder. This prevents rclone's own metadata updates from being mistaken for new local edits; unchanged files are reported as skipped rather than as uploads. At startup, DriveBridge begins watching immediately and waits for 15 seconds of local inactivity before starting its full recovery check.

Recent activity is saved locally in `drivebridge_activity.json`. The file contains filenames, timestamps, sizes, and transfer durations and is intentionally excluded from Git.

---

## Project Structure

```
DriveBridge/
├── main.py                     # App entry point: tray icon, background loops, mutex
├── Launch DriveBridge.bat      # Launcher: finds pythonw/python from PATH automatically
├── requirements.txt
│
├── core/                       # Engine, no UI imports
│   ├── config.py               # Reads/writes drivebridge_config.json
│   ├── logger.py               # In-memory ring buffer + rotating log file (512 KB cap)
│   ├── rclone_manager.py       # Quick uploads, bisync orchestration, queues, activity history
│   └── startup.py              # Windows Startup folder registration
│
├── ui/                         # All GUI windows (customtkinter)
│   ├── theme.py                # Shared colours
│   ├── activity_feed.py        # Tray dashboard: two-lane status, queue, persistent history
│   ├── settings_gui.py         # Settings panel
│   ├── conflict_ui.py          # Conflict resolver dialog
│   ├── wizard.py               # First-run setup wizard
│   └── gui_utils.py            # Window icon helper
│
└── utils/
    └── notify_utils.py         # Native Windows toast notifications
```

---

## Fresh Machine Setup

1. Install Python 3.10+ and add it to PATH
2. Install rclone
3. Clone this repo and run `pip install -r requirements.txt`
4. Run `Launch DriveBridge.bat` and follow the setup wizard

The wizard will detect if rclone is missing or if no Google Drive remote is configured, and guide you through each step.

---

## The Story Behind This

The idea started with a frustration with the official Google Drive desktop client. Marking files for offline access stores two copies: one on your main drive, one in Google's cache on C:. Delete the C: copy and it redownloads. Keep files online-only and they are inaccessible from the main PC. For someone who needed reliable sync across machines, neither option was workable.

The original plan was to build around a clear hierarchy: the PC as the main base holding everything, the laptop as a satellite that pulls files from the cloud on request. The cloud would serve as a backup layer, not the source of truth.

The laptop side proved to be genuinely complex to implement. It required rclone mounting via WinFsp, pinned folders for selective offline access, and cache management. Partway through, it became clear that the official Google Drive client's online-only mode already covers that use case well enough. The laptop implementation was dropped, the PC sync side was completed and tested, and that is what DriveBridge is today.

---

## Credits

The idea, requirements, and direction came from me. The code was written collaboratively with [Claude](https://claude.ai) and [Gemini](https://gemini.google.com) as AI coding assistants across multiple sessions.

---

## License

MIT — see [LICENSE](LICENSE)

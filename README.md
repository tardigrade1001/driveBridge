# ☁️ DriveBridge

**A lightweight Google Drive sync client for Windows. Lives in the system tray and runs quietly.**

DriveBridge wraps [`rclone bisync`](https://rclone.org/bisync/) in a polished Dropbox-style tray app. Two-way sync, live file watching, conflict resolution and mass-deletion protection, in a light client.

> **Windows only.** Requires Python 3.10+ and rclone.

---

## Features

- **Two-way bisync**: keeps a local folder and a Google Drive folder in sync, both ways
- **Quick uploads**: new and modified local files upload individually within seconds, ahead of any full-folder scan
- **Live watchdog**: detects file changes instantly, debounces repeated saves per file, and keeps batches of changed files queued separately
- **Two-lane sync engine**: separates quick uploads from slower full two-way reconciliation
- **Reconciliation safeguards**: absorbs queued quick checks during full scans, so metadata updates leave the queue counts accurate and the upload path loop-free
- **Idle-aware startup**: gives new local files priority, then starts the boot-time reconciliation after 15 seconds of local quiet
- **Persistent activity dashboard**: shows quick uploads, background checks, queue state, recent files, sizes, durations and last-sync time across restarts, and closes automatically when you click elsewhere
- **Optimized full scanning**: parallel checkers and checksum-skipping reduce reconciliation overhead
- **Automatic Conflict Resolution**: simultaneous edits resolve by "newer wins", so the file with the later modification time is kept and the other copy is replaced. One version survives, and the sync stays free of "conflict file" clutter. Keep both edits by renaming one before syncing.
- **Timestamp handling**: absorbs the 1-second timestamp rounding in Google Drive, so a file that only appears to have changed is left alone and the sync stays quiet
- **Mass deletion protection**: if a sync would delete a large number of files on Drive, it pauses and asks for confirmation before touching anything
- **Boot-sweep recovery**: runs a full reconciliation on every launch to catch changes made during downtime
- **Smart exclusions**: ignores Windows and Office lock files (`~$*`, `Thumbs.db`, `.tmp`, `desktop.ini`) that would otherwise cause endless sync loops
- **Single-instance enforcement**: native Windows mutex prevents duplicate background processes
- **Native toast notifications**: sync complete and error alerts through the Windows notification center, using the platform alone
- **Catppuccin dark theme**

---

## Requirements

- **Python 3.10+**: [python.org](https://www.python.org/downloads/)
- **rclone**: [rclone.org/downloads](https://rclone.org/downloads/)

---

## Installation

**1. Clone the repo**
```cmd
git clone https://github.com/tardigrade1001/driveBridge.git
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

On first launch, the setup wizard walks through authenticating with Google Drive and choosing a sync folder. It writes the rclone configuration for you.

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

- Creating or modifying a local file schedules a checksum-aware direct `rclone copyto` after a four-second debounce. Repeated saves reset the timer for that file alone, and multiple files remain separate queue entries.
- Deletions, renames, remote changes, startup recovery, and periodic safety checks use the full `rclone bisync` reconciliation path.

Quick uploads pause for the duration of a full reconciliation scan. This keeps the rclone metadata updates clear of the new-local-edit path, and unchanged files are reported as skipped. At startup, DriveBridge begins watching immediately and waits for 15 seconds of local quiet before starting the full recovery check.

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

The wizard detects a missing rclone or an unconfigured Google Drive remote, and guides you through each step.

---

## The Story Behind This

The idea started with a frustration with the official Google Drive desktop client. Marking files for offline access stores two copies: one on the main drive, one in the Google cache on C:. Delete the C: copy and it redownloads. Keep files online-only and they stay out of reach from the main PC. Reliable sync across machines needed a third option.

The original plan was to build around a clear hierarchy: the PC as the main base holding everything, the laptop as a satellite that pulls files from the cloud on request. The cloud would serve as a backup layer, with the PC as the source of truth.

The laptop side proved to be genuinely complex to implement. It required rclone mounting via WinFsp, pinned folders for selective offline access, and cache management. Partway through, it became clear that the online-only mode in the official Google Drive client already covers that use case well enough. The laptop implementation was dropped, the PC sync side was completed and tested, and that is what DriveBridge is today.

---

## Credits

The idea, requirements, and direction came from me. The code was written collaboratively with [Claude](https://claude.ai) and [Gemini](https://gemini.google.com) as AI coding assistants across multiple sessions.

---

## License

MIT, see [LICENSE](LICENSE)

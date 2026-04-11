# Discord Quest Completer

A simple Python script that automatically completes **Discord Game Quests** by spoofing a game process.

Discord detects which game you're playing by scanning running process names **and** checking for a visible window from that process. This script finds the correct executable name for any quest game (from Discord's own API), creates a fake process with that name, opens a real GUI window, and keeps everything alive long enough for the quest to register — no actual game installation required.

---

## Requirements

- **Windows** (the script uses Windows-only APIs)
- **Python 3.10+** — no third-party libraries needed, only the standard library  
  *(tkinter is included with Python by default)*
- **Discord** open and logged in before you start the script

To check your Python version:
```
python --version
```

If Python is not installed, download it from [python.org](https://www.python.org/downloads/). During installation, make sure **"Add Python to PATH"** is checked.

---

## How to use

### 1. Open a terminal

Press `Win + R`, type `cmd`, press Enter.  
Navigate to the folder where you saved `discord_quest.py`:
```
cd C:\path\to\CompleteDiscordQuest
```

### 2. Run the script

```
python discord_quest.py
```

### 3. Search for your quest game

When prompted, type the name of the game shown in your Discord Quest (or just part of it):

```
🔍 Enter game name (or part of it): Arena Breakout
```

### 4. Select the game and executable

The script will show a numbered list of matches. Type the number and press Enter.  
Then it will show the available `.exe` names for that game — pick the one shown (usually there's only one).

### 5. Enter the duration

Type how many minutes the process should run. Check the required playtime in the Quest description inside Discord (usually 15 minutes). Press Enter to use the default (15 minutes).

```
⏱  How many minutes to run? [15]:
```

### 6. Wait — a window will appear

A small dark window will open on your screen with the game name and a status message:

```
🎮  Arena Breakout: Infinite
Discord Quest in progress — do not close this window.
Running for 15 minute(s).
```

**Do not close this window.** If you close it manually, the script will stop.

The terminal shows a two-phase progress bar:

- **Phase 1 (first 30s):** `Waiting for Discord to detect … 60%`  
  Discord scans for new game processes every ~20–30 seconds. This buffer gives it time to find the process before the quest timer starts counting.

- **Phase 2 (remaining time):** `██████████░░░░░░░░░░░░░░░░░░░░  33%  remaining 10:00`  
  The quest playtime is counting down in Discord.

### 7. Done

Once the timer finishes, the window closes automatically, all temporary files are deleted, and your quest should be marked as complete in Discord.

---

## How it works (technical)

### Why not just fake a process name?

Discord's quest system performs **two checks** — it must see both:
1. A running process with the correct `.exe` name (e.g. `uagame.exe`)
2. A **visible window** (GUI window) belonging to that process

Additionally, Discord only tracks **Windows GUI applications** (PE subsystem = 2). Console applications like `cmd.exe` (subsystem = 3) are ignored entirely, and on Windows 11 `notepad.exe` is a Store stub that exits immediately.

### The solution: `pythonw.exe` + tkinter

1. The script fetches Discord's full list of detectable applications from the public API:  
   `https://discord.com/api/v8/applications/detectable`

2. You search for your quest game. The script finds the exact `.exe` name and directory structure Discord expects (e.g. `win64\uagame.exe`).

3. It copies **`pythonw.exe`** (the GUI-mode Python launcher, guaranteed to exist since Python is already installed) into a temporary folder under the required name — e.g. `win64\uagame.exe`.  
   `pythonw.exe` is a real Windows GUI application (PE subsystem = 2), so Discord treats it like a game.

4. A small helper script (`_quest_helper.pyw`) is created alongside it. This script opens a minimal tkinter window that stays visible for the entire duration.

5. The fake exe is launched as: `uagame.exe _quest_helper.pyw`  
   Task Manager shows the process as `uagame.exe`. Discord sees a GUI process with an active window → quest timer starts.

6. After the timer expires (or you press `Ctrl+C`), the process is terminated and the temporary folder is deleted automatically.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `python` is not recognized | Make sure Python is installed and "Add to PATH" was checked during setup |
| Quest not detected after 2+ minutes | Make sure Discord is open and logged in. Try restarting Discord |
| The game window closes immediately | Do not close it manually — wait for the timer to finish |
| Antivirus warning | The script copies `pythonw.exe` under a game name. Add an exception for the temp folder (`discord_quest_*` in `%TEMP%`) or the script itself |
| `pythonw.exe not found` | Reinstall Python from [python.org](https://www.python.org/downloads/) using the standard installer |

---

## Notes

- Works on **Windows only**.
- Does **not** modify Discord, inject into any process, or bypass client-side security. It presents a legitimate-looking GUI process that Discord's game scanner picks up naturally.
- All temporary files (`win64\uagame.exe`, `_quest_helper.pyw`, etc.) are created in `%TEMP%` and deleted automatically when done.
- Press `Ctrl+C` in the terminal at any time to stop early and clean up.

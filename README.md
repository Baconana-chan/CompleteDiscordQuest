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

### 3. Add your first quest

Press **A** to start adding a game, then type the name of the game shown in your Discord Quest (or just part of it):

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

### 6. (Optional) Create extra files for detection

Some games require additional files (like Steam `.acf` manifests) for Discord to fully register them. When prompted, you can provide the path and content:

```
Create extra file(s) required for Discord detection? [y/N]: y
Extra file path: %programFiles(x86)%/Steam/steamapps/appmanifest_2753000.acf
Confirm writing this file? [y/N]: y
Enter file content. Finish with a line containing only END:
"AppState"
{
"appid" "2753000"
"name" "GOALS"
"installdir" "GOALS"
}
END
```

If the path requires administrator privileges (e.g. inside `Program Files`), the script will offer to retry with elevation:

```
⚠  Access denied to: C:\Program Files (x86)\Steam\steamapps
Retry with administrator privileges? [y/N]: y
```

A UAC prompt will appear — click **Yes** to write the file.

### 7. A game window will appear

A small dark window will open on your screen with the game name and a progress bar:

- **Use the `+30s` / `-30s` buttons** in the window to adjust the timer on the fly
- **Do not close this window** — if you close it manually, the quest stops

### 8. Monitor in the terminal

The terminal shows a live status of all active quests:

```
  Active quests:
    1. Arena Breakout: Infinite ████████░░░░░░░░░░░░░░░░░░░░  33%  remaining 10:00  PID 12345
```

**Controls while quests are running:**
| Key | Action |
|-----|--------|
| `A` | Add another quest (run multiple games at once!) |
| `S` | Show status of all active quests |
| `V` | Open Settings GUI window |
| `Q` | Stop all quests and exit |
| `H` / `?` | Show help |

### 9. Done

Once the timer finishes, the window closes automatically, all temporary files are deleted, and your quest should be marked as complete in Discord.

---

## Settings GUI (press `V`)

At any time, press **V** to open a graphical settings window with:

- **Active Quests** — live-updating list showing each quest's progress and status
- **Search** — type to filter the full Discord game list and add games with one click
- **"Add Selected Game"** — adds a quest with default duration (no extra questions)
- **"Stop All"** — stops every active quest immediately
- **Default duration** — change the default quest length for future additions

The console is blocked while the GUI is open — just close it (✕ or press V again) to return to the terminal.

---

## Multi-Quest Mode

You can run **multiple quests simultaneously** in a single console session:

1. Press `A` to add the first game
2. While it's running, press `A` again to add another
3. The terminal shows **all** active quests with individual progress bars
4. Each quest runs independently — when one finishes, the others continue
5. Press `Q` to stop everything at once

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

4. A small helper script (`_quest_helper.pyw`) is created alongside it. This script opens a minimal tkinter window with a live progress bar and +/-30s adjustment buttons.

5. The fake exe is launched as: `uagame.exe _quest_helper.pyw`  
   Task Manager shows the process as `uagame.exe`. Discord sees a GUI process with an active window → quest timer starts.

6. After the timer expires (or you press `Ctrl+C` / `Q`), the process is terminated and the temporary folder is deleted automatically.

### Extra file support

Some games need metadata files (like Steam `appmanifest_*.acf`) before Discord will detect them. The script supports:
- Writing arbitrary files to any path (with `%programFiles(x86)%` etc. variable expansion)
- Automatic UAC elevation via PowerShell `RunAs` if the target directory is protected
- Progress tracking so you can write multiple extra files in sequence

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `python` is not recognized | Make sure Python is installed and "Add to PATH" was checked during setup |
| Quest not detected after 2+ minutes | Make sure Discord is open and logged in. Try restarting Discord. Some games need extra files — check your next prompt |
| The game window closes immediately | Do not close it manually — wait for the timer to finish |
| Antivirus warning | The script copies `pythonw.exe` under a game name. Add an exception for the temp folder (`discord_quest_*` in `%TEMP%`) or the script itself |
| `pythonw.exe not found` | Reinstall Python from [python.org](https://www.python.org/downloads/) using the standard installer |
| Access denied writing extra file | The script will ask if you want to retry with administrator privileges — say `y` and accept the UAC prompt |

---

## Notes

- Works on **Windows only**.
- Does **not** modify Discord, inject into any process, or bypass client-side security. It presents a legitimate-looking GUI process that Discord's game scanner picks up naturally.
- All temporary files are created in `%TEMP%` inside a `discord_quest_*` folder and deleted automatically when done.
- Press `Ctrl+C` in the terminal at any time to stop early and clean up.
- No third-party dependencies — uses only Python's built-in standard library.

---

## Version History

- **v1.0** — Single quest mode, basic spoofing
- **v1.1** — Multi-quest support, extra file creation, elevated write
- **v1.2** — Settings GUI (tkinter), live progress display, in-window timer adjustment
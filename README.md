# Discord Quest Completer

A simple Python script that automatically completes **Discord Game Quests** by spoofing a game process.

Discord detects which game you're playing by scanning running process names. This script finds the correct executable name for any quest game (from Discord's own API), creates a fake process with that name, and keeps it alive long enough for the quest to register — no actual game installation required.

---

## Requirements

- **Windows** (the script uses Windows-only APIs)
- **Python 3.10+** — no third-party libraries needed, only the standard library
- **Discord** open and logged in before you start the script

To check your Python version:
```
python --version
```

If Python is not installed, download it from [python.org](https://www.python.org/downloads/).

---

## How to use

### 1. Open a terminal

Press `Win + R`, type `cmd`, press Enter.  
Navigate to the folder where you saved `discord_quest.py`:
```
cd C:\path\to\discord_quest
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
Then it will show the available `.exe` names for that game — pick the one listed (usually there's only one).

### 5. Enter the duration

Type how many minutes the process should run. You can find the required playtime in the Quest description inside Discord (usually 15 minutes).  
Press Enter to use the default (15 minutes).

```
⏱  How many minutes to run? [15]:
```

### 6. Wait

The script runs a hidden process with the correct game name and shows a progress bar:

```
  ██████████░░░░░░░░░░░░░░░░░░░░  33%  remaining 10:00
```

Discord should detect the process within **20–30 seconds** and start counting playtime.  
You can leave it running in the background.

### 7. Done

Once the timer finishes, the process is stopped automatically and all temporary files are deleted. Your quest should be marked as complete in Discord.

---

## How it works (technical)

1. The script fetches the full list of Discord-detectable applications from the public API:  
   `https://discord.com/api/v8/applications/detectable`

2. You search for your quest game. The script finds the exact `.exe` name Discord expects to see (e.g. `win64/uagame.exe`).

3. It copies `cmd.exe` (a standard Windows system file) into a temporary folder under the required name (e.g. `win64\uagame.exe`). The file content doesn't matter — only the **process name** is checked by Discord.

4. It launches the fake process invisibly, running `ping -n <N> 127.0.0.1` internally as a sleep mechanism that doesn't require any user input.

5. After the timer expires (or you press `Ctrl+C`), the process is terminated and the temporary folder is deleted.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `python` is not recognized | Make sure Python is installed and added to PATH during setup |
| Quest not detected after 2+ minutes | Make sure Discord is open and you are logged in. Try closing and reopening Discord |
| Process exits immediately | Restart the script; a temporary network or system hiccup may have occurred |
| Antivirus warning | The script copies `cmd.exe` under a different name — some AV software flags this. Add an exception for the `discord_quest_*` temp folder or the script itself |

---

## Notes

- The script only works on **Windows**.
- It does **not** modify Discord, inject into any process, or bypass any client-side checks. It simply makes a process with the right name visible to Discord's game detection.
- All temporary files are created in your system `%TEMP%` folder and deleted automatically when done.
- Press `Ctrl+C` at any time to stop early.

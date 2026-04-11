"""
Discord Quest Completer
=======================
Fetches game info from Discord's detectable apps list,
creates a fake game executable, and runs it for the required duration
so Discord registers your playtime for Quest completion.

Usage:
  python discord_quest.py
"""

import os
import sys
import time
import json
import shutil
import tempfile
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────
DISCORD_API           = "https://discord.com/api/v8/applications/detectable"
DEFAULT_DURATION      = 15          # minutes
POLL_INTERVAL         = 5           # seconds between status updates
DISCORD_DETECT_BUFFER = 30          # extra seconds added so Discord detects the process before the quest timer starts

CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


# ─────────────────────────────────────────────────────────────
# Fake executable creation
# ─────────────────────────────────────────────────────────────
# Strategy: copy pythonw.exe under the game's exe name, then run it
# with a small tkinter helper script that shows a real GUI window.
#
# WHY pythonw.exe?
#   - cmd.exe / notepad.exe on Win11 are either console apps (subsystem 3)
#     or Store stubs that exit immediately.
#   - pythonw.exe is a genuine Windows GUI application (subsystem 2).
#   - It is guaranteed to exist because this script is already running Python.
#   - When renamed to uagame.exe, Task Manager and Discord both see that name.
#   - Passing it a .pyw helper keeps a real window open for Discord to track.

def find_pythonw() -> Path:
    """Return the path to pythonw.exe next to the current Python interpreter."""
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if pythonw.exists():
        return pythonw
    raise FileNotFoundError(
        f"pythonw.exe not found next to {sys.executable}. "
        "Please reinstall Python."
    )


def create_quest_window_script(
    script_path: Path, game_name: str, total_seconds: int, signal_file: Path
) -> None:
    """Write a tkinter script with a live progress bar and +/-30s buttons."""
    safe_name = game_name.replace("\\", "\\\\").replace('"', '\\"')
    sig = signal_file.as_posix().replace("\\", "/")
    lines = [
        "import sys, time, tkinter as tk",
        "from tkinter import ttk",
        "from pathlib import Path",
        "",
        f"total_init = int(sys.argv[1]) if len(sys.argv) > 1 else {total_seconds}",
        f'sig = Path(r"{signal_file}")',
        "start = time.time()",
        "state = {'extra': 0}",
        "",
        "root = tk.Tk()",
        f'root.title("{safe_name}")',
        'root.geometry("460x270")',
        "root.resizable(False, False)",
        'root.configure(bg="#1e1e2e")',
        "",
        'tk.Label(root, text="\U0001f3ae  ' + safe_name + '",',
        '         font=("Segoe UI", 13, "bold"),',
        '         bg="#1e1e2e", fg="#cdd6f4").pack(pady=(20, 4))',
        "",
        'tk.Label(root, text="Discord Quest in progress \u2014 do not close this window.",',
        '         font=("Segoe UI", 9), bg="#1e1e2e", fg="#a6adc8").pack()',
        "",
        "st = ttk.Style()",
        'st.theme_use("default")',
        'st.configure("Q.Horizontal.TProgressbar",',
        '             background="#89b4fa", troughcolor="#313244",',
        '             borderwidth=0, thickness=14)',
        "",
        'frm = tk.Frame(root, bg="#1e1e2e")',
        'frm.pack(fill="x", padx=32, pady=(14, 2))',
        'pb = ttk.Progressbar(frm, style="Q.Horizontal.TProgressbar",',
        '                     orient="horizontal", length=396,',
        '                     mode="determinate", maximum=total_init)',
        "pb.pack()",
        "",
        'tv = tk.StringVar(value="starting \u2026")',
        'tk.Label(root, textvariable=tv, font=("Segoe UI", 9),',
        '         bg="#1e1e2e", fg="#6c7086").pack(pady=(4, 0))',
        "",
        # ── +/- buttons ───────────────────────────────────────
        'bf = tk.Frame(root, bg="#1e1e2e")',
        'bf.pack(pady=(10, 0))',
        "",
        "def effective():",
        "    return total_init + state['extra']",
        "",
        "def add_time():",
        "    state['extra'] += 30",
        "    pb['maximum'] = effective()",
        "    try: sig.write_text('+30')",
        "    except Exception: pass",
        "",
        "def sub_time():",
        "    elapsed = time.time() - start",
        "    if effective() - elapsed > 35:",
        "        state['extra'] -= 30",
        "        pb['maximum'] = effective()",
        "        try: sig.write_text('-30')",
        "        except Exception: pass",
        "",
        'btn_minus = tk.Button(bf, text="\u2212 30s", command=sub_time,',
        '    font=("Segoe UI", 9, "bold"), bg="#45475a", fg="#f38ba8",',
        '    activebackground="#313244", activeforeground="#f38ba8",',
        '    relief="flat", padx=14, pady=5, cursor="hand2", bd=0)',
        'btn_minus.pack(side="left", padx=(0, 8))',
        "",
        'btn_plus = tk.Button(bf, text="+ 30s", command=add_time,',
        '    font=("Segoe UI", 9, "bold"), bg="#45475a", fg="#a6e3a1",',
        '    activebackground="#313244", activeforeground="#a6e3a1",',
        '    relief="flat", padx=14, pady=5, cursor="hand2", bd=0)',
        'btn_plus.pack(side="left")',
        "",
        # ── tick loop ─────────────────────────────────────────
        "def tick():",
        "    elapsed = time.time() - start",
        "    et = effective()",
        "    rem = max(0, et - elapsed)",
        "    pb['maximum'] = et",
        "    pb['value'] = min(elapsed, et)",
        "    m, s = divmod(int(rem), 60)",
        '    tv.set(f"{m:02d}:{s:02d} remaining")',
        "    if rem > 0:",
        "        root.after(500, tick)",
        "    else:",
        '        tv.set("Done! You may close this window.")',
        "        btn_plus.config(state='disabled')",
        "        btn_minus.config(state='disabled')",
        "",
        "root.after(500, tick)",
        "root.mainloop()",
    ]
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def print_banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════╗
║     Discord Quest Completer  v1.0            ║
║     by Baconana-chan                         ║
╚══════════════════════════════════════════════╝{RESET}
""")


def print_step(icon: str, text: str):
    print(f"  {CYAN}{icon}{RESET}  {text}")


def print_ok(text: str):
    print(f"  {GREEN}✔{RESET}  {text}")


def print_warn(text: str):
    print(f"  {YELLOW}⚠{RESET}  {text}")


def print_err(text: str):
    print(f"  {RED}✖{RESET}  {text}")


def format_seconds(s: int) -> str:
    m, sec = divmod(s, 60)
    return f"{m:02d}:{sec:02d}"


# ─────────────────────────────────────────────────────────────
# Discord API
# ─────────────────────────────────────────────────────────────
def fetch_detectable() -> list[dict]:
    print_step("🌐", f"Fetching game list from {DISCORD_API} …")
    req = urllib.request.Request(
        DISCORD_API,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    print_ok(f"Loaded {len(data)} entries.")
    return data


def search_games(apps: list[dict], query: str) -> list[dict]:
    q = query.lower()
    results = []
    for app in apps:
        name = app.get("name", "")
        aliases = app.get("aliases", [])
        all_names = [name] + (aliases if isinstance(aliases, list) else [])
        if any(q in n.lower() for n in all_names):
            results.append(app)
    return results


def get_exe_paths(app: dict) -> list[str]:
    """Extract executable paths from a detectable-app entry."""
    paths = []
    for exe in app.get("executables", []):
        name = exe.get("name", "")
        if name:
            paths.append(name)
    # Some entries store the name directly at top-level (older format)
    top = app.get("name", "")
    if top.endswith(".exe") and top not in paths:
        paths.append(top)
    return paths


# ─────────────────────────────────────────────────────────────
# Exe creation & management
# ─────────────────────────────────────────────────────────────
def resolve_exe_path(raw_name: str, base_dir: Path) -> Path:
    """
    Handle paths like:
      overwatch.exe            → <base>/overwatch.exe
      win64/uagame.exe         → <base>/win64/uagame.exe
      Binaries\\Win64\\game.exe → <base>/Binaries/Win64/game.exe
    """
    normalised = raw_name.replace("\\", "/")
    parts = normalised.split("/")
    return base_dir.joinpath(*parts)


def create_fake_exe(exe_path: Path) -> bool:
    """Copy pythonw.exe to the target path (creates any needed directories)."""
    try:
        src = find_pythonw()
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, exe_path)
        print_ok(f"Created: {exe_path}  (copied from {src})")
        return True
    except Exception as e:
        print_err(f"Failed to create file: {e}")
        return False


def kill_process(proc: subprocess.Popen):
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# Interactive selection helpers
# ─────────────────────────────────────────────────────────────
def pick_from_list(items: list, prompt: str) -> int:
    """Print a numbered list and return the chosen index (0-based)."""
    for i, item in enumerate(items, 1):
        print(f"    {DIM}[{i}]{RESET} {item}")
    while True:
        try:
            raw = input(f"\n  {BOLD}{prompt}{RESET} ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(items):
                return idx
            print_warn("Please enter a number from the list.")
        except (ValueError, EOFError):
            print_warn("Please enter a valid number.")


# ─────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────
def main():
    print_banner()

    # ── Step 1: fetch apps ───────────────────────────────────
    try:
        apps = fetch_detectable()
    except Exception as e:
        print_err(f"Failed to fetch game list: {e}")
        sys.exit(1)

    # ── Step 2: search ───────────────────────────────────────
    while True:
        print()
        query = input(f"  {BOLD}🔍 Enter game name (or part of it): {RESET}").strip()
        if not query:
            continue
        results = search_games(apps, query)
        if not results:
            print_warn("No games found. Try a different search term.")
            continue
        break

    # ── Step 3: pick game ────────────────────────────────────
    print(f"\n  Found {len(results)} game(s):\n")
    game_names = [r.get("name", "<unnamed>") for r in results]
    game_idx = pick_from_list(game_names, "Select game [number]:")
    chosen = results[game_idx]
    print_ok(f"Selected: {BOLD}{chosen.get('name')}{RESET}")

    # ── Step 4: pick exe ─────────────────────────────────────
    exe_paths = get_exe_paths(chosen)
    if not exe_paths:
        print_warn("No .exe paths found in the API data.")
        custom = input(f"  {BOLD}Enter the .exe name manually: {RESET}").strip()
        if not custom:
            print_err("No name entered, exiting.")
            sys.exit(1)
        exe_paths = [custom]

    print(f"\n  Available executables:\n")
    exe_idx = pick_from_list(exe_paths, "Select .exe [number]:")
    chosen_exe = exe_paths[exe_idx]
    print_ok(f"Selected: {BOLD}{chosen_exe}{RESET}")

    # ── Step 5: duration ─────────────────────────────────────
    print()
    dur_raw = input(
        f"  {BOLD}⏱  How many minutes to run? [{DEFAULT_DURATION}]: {RESET}"
    ).strip()
    try:
        duration_min = int(dur_raw) if dur_raw else DEFAULT_DURATION
        if duration_min <= 0:
            raise ValueError
    except ValueError:
        print_warn(f"Invalid value, using default of {DEFAULT_DURATION} min.")
        duration_min = DEFAULT_DURATION

    # ── Step 6: working directory ────────────────────────────
    base_dir = Path(tempfile.mkdtemp(prefix="discord_quest_"))
    print_ok(f"Working folder: {base_dir}")

    exe_path = resolve_exe_path(chosen_exe, base_dir)

    # ── Step 7: create file ──────────────────────────────────
    print()
    print_step("🔨", f"Creating {exe_path.name} …")
    if not create_fake_exe(exe_path):
        shutil.rmtree(base_dir, ignore_errors=True)
        sys.exit(1)

    # ── Step 8: run ──────────────────────────────────────────
    quest_seconds = duration_min * 60           # what the user asked for
    total_seconds = quest_seconds + DISCORD_DETECT_BUFFER  # includes detection buffer
    deadline = datetime.now() + timedelta(seconds=total_seconds)

    # Write the tkinter window script (needs total_seconds + signal file path)
    helper_script = base_dir / "_quest_helper.pyw"
    signal_file   = base_dir / "_adjust.txt"
    game_display_name = chosen.get("name", exe_path.stem)
    create_quest_window_script(helper_script, game_display_name, total_seconds, signal_file)
    print_ok(f"Created helper script: {helper_script.name}")

    print()
    print_step(
        "▶",
        f"Running {BOLD}{exe_path.name}{RESET} "
        f"for {BOLD}{duration_min}{RESET} min "
        f"(+{DISCORD_DETECT_BUFFER}s buffer, until {deadline.strftime('%H:%M:%S')})",
    )
    print_warn(f"Discord will have {DISCORD_DETECT_BUFFER}s to detect the process before the quest timer starts.")
    print(f"  {DIM}Press Ctrl+C to stop early.{RESET}\n")

    proc = None
    try:
        # Launch: <game>.exe (= pythonw.exe renamed) _quest_helper.pyw
        # pythonw.exe is a real GUI app (PE subsystem = 2), so Discord
        # recognises it as a game process. The helper script opens a
        # small window that stays open until we kill the process.
        proc = subprocess.Popen(
            [str(exe_path), str(helper_script), str(total_seconds)],
            cwd=str(base_dir),
        )
        print_ok(f"PID: {proc.pid}")
        print_warn("A small game window will open — do NOT close it until the timer finishes.")
        print_warn("Use the  + 30s / − 30s  buttons in the window to adjust time if needed.")

        # Progress bar tracks only the quest portion (quest_seconds).
        # The buffer at the start is silent — Discord detects the process then.
        elapsed = 0
        while elapsed < total_seconds:
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            remaining = total_seconds - elapsed

            # During the buffer phase show a "waiting for Discord" indicator
            if elapsed <= DISCORD_DETECT_BUFFER:
                detecting_pct = int(elapsed / DISCORD_DETECT_BUFFER * 100)
                print(
                    f"\r  {YELLOW}Waiting for Discord to detect …{RESET} "
                    f"{CYAN}{detecting_pct}%{RESET}   ",
                    end="",
                    flush=True,
                )
            else:
                # Progress relative to the quest portion only
                quest_elapsed = elapsed - DISCORD_DETECT_BUFFER
                quest_remaining = quest_seconds - quest_elapsed
                pct = int(quest_elapsed / quest_seconds * 30)
                bar = "█" * pct + "░" * (30 - pct)
                pct_num = int(quest_elapsed / quest_seconds * 100)
                print(
                    f"\r  {GREEN}{bar}{RESET} {pct_num:3d}%  "
                    f"remaining {YELLOW}{format_seconds(max(0, quest_remaining))}{RESET}   ",
                    end="",
                    flush=True,
                )
            # Check if the window buttons requested a time adjustment
            if signal_file.exists():
                try:
                    adj = int(signal_file.read_text().strip())
                    signal_file.unlink()
                    total_seconds  += adj
                    quest_seconds  += adj
                    sign = f"+{adj}s" if adj > 0 else f"{adj}s"
                    print(f"\n  {CYAN}⏱  Time adjusted: {sign}  "
                          f"(new total: {format_seconds(max(0, total_seconds - elapsed))}){RESET}")
                except Exception:
                    pass

            if proc.poll() is not None:
                print()
                print_warn("Process exited early (unexpected).")
                break

        print()

    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}Stopped by user.{RESET}")
    finally:
        if proc and proc.poll() is None:
            print_step("⏹", "Stopping process …")
            kill_process(proc)
            print_ok("Process stopped.")
        # cleanup
        print_step("🗑", "Removing temporary folder …")
        shutil.rmtree(base_dir, ignore_errors=True)
        print_ok("Done! The quest should register in Discord.")


if __name__ == "__main__":
    # Enable ANSI colours on Windows
    if sys.platform == "win32":
        os.system("color")
    main()

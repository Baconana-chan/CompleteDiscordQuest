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
# Strategy: copy cmd.exe (a real Windows binary) to the target path.
# When launched, the PROCESS NAME will be e.g. "uagame.exe" — which
# is exactly what Discord checks. We pass it a ping command so it
# sleeps silently for the required duration without touching stdin.

def find_system_exe() -> Path:
    """Return the path to cmd.exe (always present on Windows)."""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidate = windir / "System32" / "cmd.exe"
    if candidate.exists():
        return candidate
    raise FileNotFoundError("cmd.exe not found — this is very unexpected.")


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
    """Copy cmd.exe to the target path (and create any needed directories)."""
    try:
        src = find_system_exe()
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
        # Strategy: run the fake exe (which is cmd.exe renamed) with a ping
        # command. "ping -n N 127.0.0.1" sends N packets with 1-second gaps,
        # giving us ~N seconds of sleep without touching stdin at all.
        # CREATE_NO_WINDOW keeps the process fully invisible.
        ping_count = total_seconds + 1  # N packets → N-1 seconds; +1 gives exactly N seconds
        proc = subprocess.Popen(
            [str(exe_path), "/c", f"ping -n {ping_count} 127.0.0.1"],
            cwd=str(base_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print_ok(f"PID: {proc.pid}")

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

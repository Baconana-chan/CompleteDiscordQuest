"""
Discord Quest Completer  v1.3
=============================
Fetches game info from Discord's detectable apps list,
creates a fake game executable, and runs it for the required duration
so Discord registers your playtime for Quest completion.

Usage:
  python discord_quest.py

Requirements: Windows, Python 3.10+, no third-party packages.
"""

import os
import sys
import time
import json
import shutil
import tempfile
import subprocess
import urllib.request
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import msvcrt
except ImportError:
    msvcrt = None

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────
DISCORD_API           = "https://discord.com/api/v10/applications/detectable"
DEFAULT_DURATION      = 15          # minutes
POLL_INTERVAL         = 5           # seconds between status updates
DISCORD_DETECT_BUFFER = 30          # extra seconds so Discord detects the process
VERSION               = "1.3"

CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


# ─────────────────────────────────────────────────────────────
# Backend: helpers
# ─────────────────────────────────────────────────────────────
def print_banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════╗
║     Discord Quest Completer  v1.3            ║
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

def print_session_help():
    print(f"  {DIM}Controls: A add game, S status, V settings GUI, Q stop all and quit, Ctrl+C stop all.{RESET}")


# ─────────────────────────────────────────────────────────────
# Backend: Discord API
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
    paths = []
    for exe in app.get("executables", []):
        name = exe.get("name", "")
        if name:
            paths.append(name)
    top = app.get("name", "")
    if top.endswith(".exe") and top not in paths:
        paths.append(top)
    return paths


# ─────────────────────────────────────────────────────────────
# Backend: Steam API
# ─────────────────────────────────────────────────────────────
def search_steam(query: str) -> list[dict]:
    """Search Steam Store for matching games.
    Returns list of {name, appid, platforms}."""
    url = f"https://store.steampowered.com/api/storesearch?term={urllib.parse.quote(query)}&cc=US&l=en&json=1"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    results = []
    for item in data.get("items", []):
        if item.get("type") == "app":
            results.append({
                "name": item.get("name", ""),
                "appid": str(item.get("id", "")),
                "platforms": item.get("platforms", {}),
            })
    return results


def find_steam_dir() -> Optional[Path]:
    """Locate Steam installation directory.
    Checks Program Files, registry, and environment variables."""
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Steam",
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Steam",
    ]
    # Try registry
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\\WOW6432Node\\Valve\\Steam") as key:
            val = winreg.QueryValueEx(key, "InstallPath")[0]
            candidates.insert(0, Path(val))
    except Exception:
        pass

    for path in candidates:
        steamapps = path / "steamapps"
        if steamapps.is_dir():
            return path
    return None


# ─────────────────────────────────────────────────────────────
# Backend: Steam manifest helpers
# ─────────────────────────────────────────────────────────────
def _steam_game_name_to_dir(name: str) -> str:
    """Convert a Steam game name to the install directory name.
    Steam usually keeps names as-is, but strips trailing whitespace."""
    return name.strip()


def create_steam_manifest(
    appid: str,
    game_name: str,
    install_dir: str,
    steam_apps_path: Path,
) -> bool:
    """Create a Steam appmanifest_<appid>.acf file.

    This tells Discord (via Steam detection) that the game is installed.
    Returns True on success.
    """
    manifest = (
        '"AppState"\n'
        '{\n'
        f'\t"appid"\t\t"{appid}"\n'
        f'\t"name"\t\t"{game_name}"\n'
        f'\t"installdir"\t"{install_dir}"\n'
        f'\t"StateFlags"\t"4"\n'
        f'\t"LastUpdated"\t"{int(time.time())}"\n'
        f'\t"UpdateResult"\t"0"\n'
        f'\t"SizeOnDisk"\t"1000000"\n'
        f'\t"buildid"\t"12345678"\n'
        '}\n'
    )
    manifest_path = steam_apps_path / f"appmanifest_{appid}.acf"
    return write_extra_file(manifest_path, manifest)


# ─────────────────────────────────────────────────────────────
# Backend: fake executable creation
# ─────────────────────────────────────────────────────────────
def find_pythonw() -> Path:
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if pythonw.exists():
        return pythonw
    raise FileNotFoundError(
        f"pythonw.exe not found next to {sys.executable}. "
        "Please reinstall Python."
    )

def resolve_exe_path(raw_name: str, base_dir: Path) -> Path:
    normalised = raw_name.replace("\\", "/")
    parts = normalised.split("/")
    return base_dir.joinpath(*parts)

def resolve_extra_path(raw_path: str, base_dir: Path) -> Path:
    expanded = os.path.expandvars(raw_path.strip())
    path = Path(expanded)
    if not path.is_absolute():
        path = base_dir / path
    return path


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
        'tk.Label(root, text="\\U0001f3ae  ' + safe_name + '",',
        '         font=("Segoe UI", 13, "bold"),',
        '         bg="#1e1e2e", fg="#cdd6f4").pack(pady=(20, 4))',
        "",
        'tk.Label(root, text="Discord Quest in progress \\u2014 do not close this window.",',
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
        'tv = tk.StringVar(value="starting \\u2026")',
        'tk.Label(root, textvariable=tv, font=("Segoe UI", 9),',
        '         bg="#1e1e2e", fg="#6c7086").pack(pady=(4, 0))',
        "",
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
        'btn_minus = tk.Button(bf, text="\\u2212 30s", command=sub_time,',
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
# Backend: elevated operations
# ─────────────────────────────────────────────────────────────
def _elevated_copy_file(src: Path, dst: Path) -> bool:
    """Copy a file via elevated cmd.exe (bypasses access denied)."""
    bat = tempfile.NamedTemporaryFile(mode="w", suffix=".bat", delete=False, encoding="utf-8")
    bat.write(
        '@echo off\n'
        f'copy /y "{src}" "{dst}" >nul\n'
        f'del /f /q "%~f0" >nul 2>&1\n'
    )
    bat_path = bat.name
    bat.close()
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             f'Start-Process cmd -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList \'/c "{bat_path}"\''],
            check=True, timeout=30,
        )
        return dst.exists()
    except Exception as e:
        print_err(f"Elevated copy failed: {e}")
        return False
    finally:
        try:
            if os.path.exists(bat_path):
                os.unlink(bat_path)
        except Exception:
            pass


def _elevated_mkdir(dir_path: Path) -> bool:
    """Create a directory tree using elevated cmd.exe (bypasses access denied)."""
    bat = tempfile.NamedTemporaryFile(mode="w", suffix=".bat", delete=False, encoding="utf-8")
    bat.write(
        '@echo off\n'
        f'if not exist "{dir_path}" mkdir "{dir_path}"\n'
        f'del /f /q "%~f0" >nul 2>&1\n'
    )
    bat_path = bat.name
    bat.close()
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             f'Start-Process cmd -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList \'/c "{bat_path}"\''],
            check=True, timeout=30,
        )
        return dir_path.exists()
    except Exception as e:
        print_err(f"Failed to create directories: {e}")
        return False
    finally:
        try:
            if os.path.exists(bat_path):
                os.unlink(bat_path)
        except Exception:
            pass


def _grant_user_execute(file_path: Path) -> None:
    """Grant the current user read & execute permission via icacls.

    After an elevated (admin) process creates a file, the current non-elevated
    user may not have execute rights.  This fixes the ACL so subprocess.Popen
    can launch the file without admin privileges.
    """
    try:
        username = os.environ.get("USERNAME", "")
        domain = os.environ.get("USERDOMAIN", "")
        if not username:
            return
        user = f'{domain}\\{username}' if domain else username
        subprocess.run(
            ["icacls", str(file_path), "/grant", f"{user}:(RX)", "/q"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass  # non-critical


def write_extra_file_elevated(extra_path: Path, content: str | bytes) -> bool:
    """Write content to a file via elevated PowerShell (bypasses access denied)."""
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        content_bytes = content
    tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".tmp", delete=False)
    tmp.write(content_bytes)
    tmp_path = Path(tmp.name)
    tmp.close()

    ps = tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8")
    tgt = str(extra_path)
    src = str(tmp_path)
    ps_path = Path(ps.name)
    ps.write(
        "$target = '" + tgt.replace("'", "''") + "'\n"
        + "$source = '" + src.replace("'", "''") + "'\n"
        + "$parent = [System.IO.Path]::GetDirectoryName($target)\n"
        + "[System.IO.Directory]::CreateDirectory($parent) | Out-Null\n"
        + "[System.IO.File]::Copy($source, $target, $true)\n"
        + "Remove-Item -LiteralPath $source -Force\n"
        + "Remove-Item -LiteralPath '" + str(ps_path).replace("'", "''") + "' -Force\n"
    )
    ps.close()

    bat = tempfile.NamedTemporaryFile(mode="w", suffix=".bat", delete=False, encoding="utf-8")
    bat.write(
        '@echo off\n'
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{ps_path}"\n'
        f'del /f /q "{ps_path}" >nul 2>&1\n'
        f'del /f /q "%~f0" >nul 2>&1\n'
    )
    bat_path = bat.name
    bat.close()

    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             f'Start-Process cmd -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList \'/c "{bat_path}"\''],
            check=True, timeout=120,
        )
        return extra_path.exists()
    except Exception as e:
        print_err(f"Elevated write failed: {e}")
        return False
    finally:
        for p in (tmp_path, ps_path, bat_path):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


def write_extra_file(extra_path: Path, content: str) -> bool:
    try:
        extra_path.parent.mkdir(parents=True, exist_ok=True)
        extra_path.write_text(content, encoding="utf-8")
        print_ok(f"Created extra file: {extra_path}")
        return True
    except PermissionError:
        print_warn(f"Access denied to: {extra_path.parent}")
        retry = input(
            f"  {BOLD}Retry with administrator privileges? [y/N]: {RESET}"
        ).strip().lower()
        if retry in ("y", "yes", "д", "да"):
            return write_extra_file_elevated(extra_path, content)
        print_warn("Extra file skipped.")
        return False
    except Exception as e:
        print_err(f"Failed to create extra file: {e}")
        return False


def create_fake_exe(exe_path: Path, for_gui: bool = False) -> bool:
    """Copy pythonw.exe to the target path.

    First tries a normal (non-elevated) copy.  If that fails with
    PermissionError, falls back to elevated cmd.exe.  After an elevated
    copy, fixes the file ACL so the current non-elevated user can launch it.
    """
    src = find_pythonw()

    # Attempt a non-elevated copy first
    try:
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, exe_path)
        print_ok(f"Created: {exe_path}  (copy from {src})")
        return True
    except PermissionError:
        pass
    except Exception as e:
        print_warn(f"Normal copy failed ({e}), trying elevated …")

    print_warn(f"Elevated creation required for: {exe_path}")
    _elevated_mkdir(exe_path.parent)
    print_step("🔨", f"Copying {exe_path.name} via elevated cmd (UAC prompt) …")
    success = _elevated_copy_file(src, exe_path)
    if success:
        # Fix ACL so the current user can execute without admin rights
        _grant_user_execute(exe_path)
        print_ok(f"Created: {exe_path}  (elevated copy from {src})")
        return True
    # If elevated copy also failed, try the PowerShell fallback
    print_warn("Elevated cmd copy failed, trying PowerShell fallback …")
    with open(src, "rb") as f:
        binary = f.read()
    result = write_extra_file_elevated(exe_path, binary)
    if result:
        _grant_user_execute(exe_path)
    return result


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
# Backend: QuestRun
# ─────────────────────────────────────────────────────────────
@dataclass
class QuestRun:
    name: str
    exe_name: str
    base_dir: Path
    proc: subprocess.Popen
    quest_seconds: int
    total_seconds: int
    started_at: float
    signal_file: Path
    completed: bool = False
    early_exit: bool = False
    finished: bool = False
    ended_at: float = 0.0

    @property
    def elapsed(self) -> float:
        end = self.ended_at or time.monotonic()
        return end - self.started_at

    def read_signal(self, elapsed: float) -> None:
        if not self.signal_file.exists():
            return
        try:
            adj = int(self.signal_file.read_text(encoding="utf-8").strip())
            self.signal_file.unlink()
            self.total_seconds += adj
            self.quest_seconds += adj
            sign = f"+{adj}s" if adj > 0 else f"{adj}s"
            print(f"\n  {CYAN}⏱  {self.name}: time adjusted: {sign}  "
                  f"(new remaining: {format_seconds(max(0, int(self.total_seconds - elapsed)))}){RESET}")
        except Exception:
            pass

    def update(self) -> None:
        if self.finished:
            return
        now = time.monotonic()
        self.ended_at = now
        elapsed = now - self.started_at
        self.read_signal(elapsed)

        if self.proc.poll() is not None:
            self.finished = True
            if elapsed < self.total_seconds - 1:
                self.early_exit = True
            return

        if elapsed >= self.total_seconds:
            kill_process(self.proc)
            self.finished = True
            self.completed = True
            return

        self.ended_at = 0.0

    def cleanup(self) -> None:
        if self.proc.poll() is None:
            kill_process(self.proc)
        shutil.rmtree(self.base_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────
# TUI helpers (console-based)
# ─────────────────────────────────────────────────────────────
def read_console_key(timeout: float) -> Optional[str]:
    if msvcrt is None:
        time.sleep(timeout)
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if msvcrt.kbhit():
            ch = msvcrt.getwche()
            if ch in ("\x00", "\xe0"):
                msvcrt.getwche()
                continue
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch
        time.sleep(0.2)
    return None


def render_run(run: QuestRun, index: int) -> str:
    elapsed = run.elapsed
    if run.completed:
        return f"{index}. {run.name} {GREEN}done{RESET} ({format_seconds(int(elapsed))})"
    if run.early_exit or run.proc.poll() is not None:
        return f"{index}. {run.name} {RED}stopped early{RESET}"
    if elapsed <= DISCORD_DETECT_BUFFER:
        pct = int(min(100, elapsed / DISCORD_DETECT_BUFFER * 100))
        return (
            f"{index}. {run.name} {YELLOW}waiting for Discord{RESET} {pct:3d}%  "
            f"PID {run.proc.pid}"
        )
    quest_elapsed = elapsed - DISCORD_DETECT_BUFFER
    quest_remaining = run.quest_seconds - quest_elapsed
    pct = int(quest_elapsed / run.quest_seconds * 100)
    bar_len = int(quest_elapsed / run.quest_seconds * 30)
    bar = "█" * max(0, min(30, bar_len)) + "░" * (30 - max(0, min(30, bar_len)))
    return (
        f"{index}. {run.name} {GREEN}{bar}{RESET} {pct:3d}%  "
        f"remaining {YELLOW}{format_seconds(max(0, int(quest_remaining)))}{RESET}  "
        f"PID {run.proc.pid}"
    )


def cleanup_finished(active: list[QuestRun]) -> list[QuestRun]:
    remaining = []
    for run in active:
        run.update()
        if run.finished:
            print()
            if run.completed:
                print_ok(f"{run.name}: quest time finished.")
            else:
                print_warn(f"{run.name}: process exited early.")
            run.cleanup()
        else:
            remaining.append(run)
    return remaining


def stop_all(active: list[QuestRun]) -> None:
    for run in active:
        print_step("⏹", f"Stopping {run.name} …")
        run.cleanup()
    print_ok("All active quests stopped.")


def pick_from_list(items: list, prompt: str) -> int:
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
# Console UI: create extra files
# ─────────────────────────────────────────────────────────────
def read_multiline_content() -> str:
    print(f"  {DIM}Enter file content. Finish with a line containing only END:{RESET}")
    lines = []
    while True:
        line = input()
        if line == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def create_extra_files(base_dir: Path) -> bool:
    while True:
        answer = input(
            f"  {BOLD}Create extra file(s) required for Discord detection? [y/N]: {RESET}"
        ).strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            return True

        raw_path = input(f"  {BOLD}Extra file path: {RESET}").strip()
        if not raw_path:
            print_warn("Extra file path cannot be empty.")
            continue

        extra_path = resolve_extra_path(raw_path, base_dir)
        print_warn(f"Target path: {extra_path}")
        confirm = input(f"  {BOLD}Confirm writing this file? [y/N]: {RESET}").strip().lower()
        if confirm not in ("y", "yes", "д", "да"):
            print_warn("Extra file skipped.")
            continue

        content = read_multiline_content()
        if not write_extra_file(extra_path, content):
            retry = input(f"  {BOLD}Try again? [y/N]: {RESET}").strip().lower()
            if retry in ("y", "yes", "д", "да"):
                continue
            return False

        more = input(f"  {BOLD}Add another extra file? [y/N]: {RESET}").strip().lower()
        if more not in ("y", "yes", "д", "да"):
            print_warn("Restart Discord after creating extra file(s), then launch the game.")
            return True


# ─────────────────────────────────────────────────────────────
# Console UI: add quest
# ─────────────────────────────────────────────────────────────
def add_quest(apps: list[dict]) -> Optional[QuestRun]:
    print(f"\n  {BOLD}Add a new quest:{RESET}")

    chosen: dict | None = None
    chosen_exe: str | None = None
    chosen_name: str = ""
    use_steam: bool = False
    steam_dir: Path | None = None
    appid: str = ""

    while True:
        print()
        query = input(f"  {BOLD}🔍 Enter game name (or part of it): {RESET}").strip()
        if not query:
            continue

        # Search Discord API first
        results = search_games(apps, query)

        if not results:
            # Nothing found in Discord — offer Steam search
            print_warn("No games found in Discord database.")
            steam_q = input(f"  {BOLD}Search Steam instead? [y/N]: {RESET}").strip().lower()
            if steam_q in ("y", "yes", "д", "да"):
                print_step("🔍", f"Searching Steam for \"{query}\" …")
                try:
                    steam_results = search_steam(query)
                except Exception as e:
                    print_err(f"Steam search failed: {e}")
                    continue
                if not steam_results:
                    print_warn("No games found on Steam either.")
                    continue
                # Filter to only Windows games
                win_results = [g for g in steam_results if g.get("platforms", {}).get("windows")]
                if not win_results:
                    win_results = steam_results
                print(f"\n  Found {len(win_results)} game(s) on Steam:\n")
                game_names = [f"{g['name']}  (ID: {g['appid']})" for g in win_results]
                game_idx = pick_from_list(game_names, "Select game [number]:")
                steam_game = win_results[game_idx]
                chosen_name = steam_game["name"]
                appid = steam_game["appid"]
                print_ok(f"Selected: {BOLD}{chosen_name}{RESET}  (Steam AppID: {appid})")

                # Ask for executable name
                exe_name = input(f"  {BOLD}Executable name [game.exe]: {RESET}").strip()
                if not exe_name:
                    exe_name = "game.exe"
                chosen_exe = exe_name
                use_steam = True

                # Find Steam directory
                steam_dir = find_steam_dir()
                if steam_dir is None:
                    print_warn("Steam installation not found. Will create files in temp directory.")
                    use_steam = False
                else:
                    print_ok(f"Steam found at: {steam_dir}")
                    # We'll create the manifest and exe in Steam directory below
            else:
                continue
            break
        else:
            # Found in Discord API
            print(f"\n  Found {len(results)} game(s):\n")
            game_names = [r.get("name", "<unnamed>") for r in results]
            game_idx = pick_from_list(game_names, "Select game [number]:")
            chosen = results[game_idx]
            chosen_name = chosen.get("name", "")
            print_ok(f"Selected: {BOLD}{chosen_name}{RESET}")

            exe_paths = get_exe_paths(chosen)
            if not exe_paths:
                print_warn("No .exe paths found in the API data.")
                steam_q = input(f"  {BOLD}Search Steam? or Enter .exe name manually? [S/manual]: {RESET}").strip().lower()
                if steam_q in ("s", "steam", "y", "yes", "д", "да"):
                    print_step("🔍", f"Searching Steam for \"{chosen_name}\" …")
                    try:
                        steam_results = search_steam(chosen_name)
                    except Exception as e:
                        print_err(f"Steam search failed: {e}")
                        custom = input(f"  {BOLD}Enter the .exe name manually: {RESET}").strip()
                        if not custom:
                            print_err("No name entered.")
                            return None
                        exe_paths = [custom]
                    else:
                        if not steam_results:
                            print_warn("No games found on Steam.")
                            custom = input(f"  {BOLD}Enter the .exe name manually: {RESET}").strip()
                            if not custom:
                                print_err("No name entered.")
                                return None
                            exe_paths = [custom]
                        else:
                            win_results = [g for g in steam_results if g.get("platforms", {}).get("windows")]
                            if not win_results:
                                win_results = steam_results
                            print(f"\n  Found {len(win_results)} game(s) on Steam:\n")
                            game_names = [f"{g['name']}  (ID: {g['appid']})" for g in win_results]
                            game_idx = pick_from_list(game_names, "Select game [number]:")
                            steam_game = win_results[game_idx]
                            appid = steam_game["appid"]
                            chosen_name = steam_game["name"]
                            print_ok(f"Selected: {BOLD}{chosen_name}{RESET}  (Steam AppID: {appid})")
                            exe_name = input(f"  {BOLD}Executable name [game.exe]: {RESET}").strip()
                            if not exe_name:
                                exe_name = "game.exe"
                            chosen_exe = exe_name
                            use_steam = True
                            steam_dir = find_steam_dir()
                            if steam_dir is None:
                                print_warn("Steam installation not found. Will use temp directory.")
                                use_steam = False
                            else:
                                print_ok(f"Steam found at: {steam_dir}")
                            exe_paths = [exe_name]
                else:
                    custom = input(f"  {BOLD}Enter the .exe name manually: {RESET}").strip()
                    if not custom:
                        print_err("No name entered.")
                        return None
                    exe_paths = [custom]

            # If already configured via Steam, skip re-asking
            if not use_steam:
                print(f"\n  Available executables:\n")
                exe_idx = pick_from_list(exe_paths, "Select .exe [number]:")
                chosen_exe = exe_paths[exe_idx]
            print_ok(f"Selected: {BOLD}{chosen_exe}{RESET}")
            break

    # ── Duration ────────────────────────────────────────────
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

    # ── Create files ────────────────────────────────────────
    helper_dir = Path(tempfile.mkdtemp(prefix="discord_quest_"))

    if use_steam and steam_dir is not None:
        # Place exe in Steam directory for better detection
        install_dir = _steam_game_name_to_dir(chosen_name)
        steam_exe_path = steam_dir / "steamapps" / "common" / install_dir / chosen_exe
        print_ok(f"Steam install path: {steam_exe_path.parent}")

        print_step("🔨", f"Creating {chosen_exe} in Steam directory …")
        if not create_fake_exe(steam_exe_path):
            shutil.rmtree(helper_dir, ignore_errors=True)
            return None

        # Create Steam manifest
        steam_apps = steam_dir / "steamapps"
        print_step("📄", "Creating Steam manifest …")
        create_steam_manifest(appid, chosen_name, install_dir, steam_apps)

        exe_path = steam_exe_path
        base_dir = helper_dir  # helper script stays in temp dir
    else:
        exe_path = resolve_exe_path(chosen_exe, helper_dir)
        base_dir = helper_dir

        print()
        print_step("🔨", f"Creating {exe_path.name} …")
        if not create_fake_exe(exe_path):
            shutil.rmtree(base_dir, ignore_errors=True)
            return None

        if not create_extra_files(base_dir):
            shutil.rmtree(base_dir, ignore_errors=True)
            return None

    # ── Prepare and launch ──────────────────────────────────
    quest_seconds = duration_min * 60
    total_seconds = quest_seconds + DISCORD_DETECT_BUFFER
    deadline = datetime.now() + timedelta(seconds=total_seconds)

    helper_script = helper_dir / "_quest_helper.pyw"
    signal_file = helper_dir / "_adjust.txt"
    create_quest_window_script(helper_script, chosen_name, total_seconds, signal_file)
    print_ok(f"Created helper script: {helper_script.name}")

    print()
    print_step(
        "▶",
        f"Running {BOLD}{exe_path.name}{RESET} "
        f"for {BOLD}{duration_min}{RESET} min "
        f"(+{DISCORD_DETECT_BUFFER}s buffer, until {deadline.strftime('%H:%M:%S')})",
    )
    print_warn(f"Discord will have {DISCORD_DETECT_BUFFER}s to detect the process before the quest timer starts.")

    try:
        proc = subprocess.Popen(
            [str(exe_path), str(helper_script), str(total_seconds)],
            cwd=str(base_dir),
        )
    except Exception as e:
        print_err(f"Failed to start quest: {e}")
        shutil.rmtree(helper_dir, ignore_errors=True)
        return None

    print_ok(f"PID: {proc.pid}")
    print_warn("A small game window will open — do NOT close it until the timer finishes.")
    print_warn("Use the  + 30s / − 30s  buttons in the window to adjust time if needed.")

    return QuestRun(
        name=chosen_name,
        exe_name=exe_path.name,
        base_dir=helper_dir,
        proc=proc,
        quest_seconds=quest_seconds,
        total_seconds=total_seconds,
        started_at=time.monotonic(),
        signal_file=signal_file,
    )


# ─────────────────────────────────────────────────────────────
# Settings GUI (tkinter)
# ─────────────────────────────────────────────────────────────
def open_settings_gui(apps: list[dict], active_ref: list) -> None:
    """Open a tkinter settings window (modal — console input is paused until closed)."""
    import tkinter as tk
    from tkinter import ttk

    window = tk.Tk()
    window.title("⚙  Discord Quest — Settings")
    window.geometry("720x560")
    window.resizable(True, True)
    window.configure(bg="#1e1e2e")

    font_title = ("Segoe UI", 12, "bold")
    font_normal = ("Segoe UI", 10)
    font_small = ("Segoe UI", 9)

    # ── Active quests ──
    tk.Label(window, text="Active Quests", font=font_title,
             bg="#1e1e2e", fg="#cdd6f4").pack(pady=(10, 2))

    active_frame = tk.Frame(window, bg="#1e1e2e", relief="sunken", bd=1)
    active_frame.pack(fill="x", padx=16, pady=(0, 8))

    active_listbox = tk.Listbox(
        active_frame, height=5, font=font_small,
        bg="#313244", fg="#cdd6f4", selectbackground="#45475a",
        selectforeground="#cdd6f4", relief="flat", borderwidth=0,
    )
    active_listbox.pack(fill="both", padx=4, pady=4, expand=True)

    def refresh_active_display():
        active_listbox.delete(0, tk.END)
        for run in active_ref:
            if run.completed:
                status = f"✅ {run.name} — done ({format_seconds(int(run.elapsed))})"
            elif run.early_exit or (run.proc.poll() is not None):
                status = f"❌ {run.name} — stopped early"
            elif run.elapsed <= DISCORD_DETECT_BUFFER:
                pct = int(min(100, run.elapsed / DISCORD_DETECT_BUFFER * 100))
                status = f"⏳ {run.name} — waiting for Discord {pct}%"
            else:
                qe = run.elapsed - DISCORD_DETECT_BUFFER
                qr = run.quest_seconds - qe
                pct = int(qe / run.quest_seconds * 100)
                status = f"▶ {run.name} — {pct}% ({format_seconds(max(0, int(qr)))} left)"
            active_listbox.insert(tk.END, status)
        window.after(2000, refresh_active_display)

    refresh_active_display()

    ttk.Separator(window, orient="horizontal").pack(fill="x", padx=16, pady=4)

    # ── Search ──
    search_frame = tk.Frame(window, bg="#1e1e2e")
    search_frame.pack(fill="x", padx=16, pady=(6, 2))

    tk.Label(search_frame, text="Find a game:", font=font_normal,
             bg="#1e1e2e", fg="#a6adc8").pack(side="left")

    search_var = tk.StringVar()
    search_entry = tk.Entry(
        search_frame, textvariable=search_var, font=font_normal,
        bg="#45475a", fg="#cdd6f4", insertbackground="#cdd6f4",
        relief="flat", bd=6, width=40,
    )
    search_entry.pack(side="left", padx=(8, 0))
    search_entry.focus()

    results_frame = tk.Frame(window, bg="#1e1e2e", relief="sunken", bd=1)
    results_frame.pack(fill="both", padx=16, pady=(0, 6), expand=True)

    results_listbox = tk.Listbox(
        results_frame, height=8, font=font_small,
        bg="#313244", fg="#cdd6f4", selectbackground="#89b4fa",
        selectforeground="#1e1e2e", relief="flat", borderwidth=0,
    )
    results_listbox.pack(fill="both", padx=4, pady=4, expand=True)

    results_data: list[dict] = []

    def do_search(*_):
        query = search_var.get().strip().lower()
        results_listbox.delete(0, tk.END)
        results_data.clear()
        if not query:
            return
        for app in apps:
            name = app.get("name", "")
            aliases = app.get("aliases", [])
            all_names = [name] + (aliases if isinstance(aliases, list) else [])
            if any(query in n.lower() for n in all_names):
                results_listbox.insert(tk.END, name)
                results_data.append(app)

    search_var.trace_add("write", do_search)

    # ── Config ──
    config_frame = tk.LabelFrame(
        window, text="Quest Config (optional — defaults used if empty)",
        font=font_small, bg="#1e1e2e", fg="#a6adc8", padx=8, pady=4,
    )
    config_frame.pack(fill="x", padx=16, pady=(4, 2))

    row1 = tk.Frame(config_frame, bg="#1e1e2e")
    row1.pack(fill="x", pady=(4, 2))
    tk.Label(row1, text="Executable path:", font=font_small,
             bg="#1e1e2e", fg="#a6adc8").pack(side="left")
    cfg_exe_var = tk.StringVar()
    cfg_exe_entry = tk.Entry(row1, textvariable=cfg_exe_var, font=font_small,
                             bg="#45475a", fg="#cdd6f4", insertbackground="#cdd6f4",
                             relief="flat", bd=4)
    cfg_exe_entry.pack(side="left", padx=(6, 16), fill="x", expand=True)
    tk.Label(row1, text="Duration (min):", font=font_small,
             bg="#1e1e2e", fg="#a6adc8").pack(side="left")
    cfg_dur_var = tk.StringVar()
    cfg_dur_entry = tk.Entry(row1, textvariable=cfg_dur_var, font=font_small,
                             width=6, bg="#45475a", fg="#cdd6f4",
                             insertbackground="#cdd6f4", relief="flat", bd=4)
    cfg_dur_entry.pack(side="left", padx=(6, 0))

    cfg_extra_files: list[dict] = []

    extra_frame = tk.Frame(config_frame, bg="#1e1e2e")
    extra_frame.pack(fill="x", pady=(2, 2))

    def rebuild_extra_rows():
        for w in extra_frame.winfo_children():
            w.destroy()
        for idx, ef in enumerate(cfg_extra_files):
            row = tk.Frame(extra_frame, bg="#313244", bd=1, relief="solid")
            row.pack(fill="x", pady=1, ipady=1)
            pf = tk.Frame(row, bg="#313244")
            pf.pack(fill="x", padx=4, pady=(2, 0))
            tk.Label(pf, text="Extra path:", font=font_small,
                     bg="#313244", fg="#a6adc8").pack(side="left")
            pv = tk.StringVar(value=ef["path"])
            pe = tk.Entry(pf, textvariable=pv, font=font_small,
                          bg="#45475a", fg="#cdd6f4", insertbackground="#cdd6f4",
                          relief="flat", bd=4)
            pe.pack(side="left", padx=(6, 0), fill="x", expand=True)
            cf = tk.Frame(row, bg="#313244")
            cf.pack(fill="x", padx=4, pady=(1, 2))
            tk.Label(cf, text="Content:", font=font_small,
                     bg="#313244", fg="#a6adc8").pack(side="left", anchor="n")
            ct = tk.Text(cf, height=3, font=font_small,
                         bg="#45475a", fg="#cdd6f4", insertbackground="#cdd6f4",
                         relief="flat", bd=4, wrap="word")
            ct.pack(side="left", padx=(6, 0), fill="x", expand=True)
            ct.insert("1.0", ef["content"])
            def upd(idx, pv, ct):
                cfg_extra_files[idx]["path"] = pv.get()
                cfg_extra_files[idx]["content"] = ct.get("1.0", "end-1c")
            pv.trace_add("write", lambda *_, i=idx, p=pv, c=ct: upd(i, p, c))
            ct.bind("<KeyRelease>", lambda e, i=idx, p=pv, c=ct: upd(i, p, c))
            def dlt(i):
                cfg_extra_files.pop(i)
                rebuild_extra_rows()
            tk.Button(row, text="✕", command=lambda i=idx: dlt(i),
                      font=font_small, bg="#f38ba8", fg="#1e1e2e",
                      activebackground="#e64553", activeforeground="#1e1e2e",
                      relief="flat", bd=0, padx=6, pady=1, cursor="hand2",
                      ).pack(side="right", anchor="ne", padx=(4, 4), pady=(2, 0))

    tk.Button(config_frame, text="+ Add extra file", font=font_small,
              bg="#45475a", fg="#a6e3a1", activebackground="#313244",
              activeforeground="#a6e3a1", relief="flat", padx=10, pady=2,
              cursor="hand2", bd=0,
              command=lambda: (cfg_extra_files.append({"path": "", "content": ""}),
                               rebuild_extra_rows()),
              ).pack(pady=(0, 4), anchor="w")

    # ── Buttons ──
    btn_frame = tk.Frame(window, bg="#1e1e2e")
    btn_frame.pack(fill="x", padx=16, pady=(0, 10))

    def on_add_selected():
        sel = results_listbox.curselection()
        if not sel:
            print_warn("Select a game from the list first.")
            return
        app = results_data[sel[0]]

        chosen_exe = cfg_exe_var.get().strip()
        if not chosen_exe:
            api_paths = get_exe_paths(app)
            if api_paths:
                chosen_exe = api_paths[0]
            else:
                chosen_exe = app.get("name", "game.exe")

        dur_raw = cfg_dur_var.get().strip()
        try:
            duration_min = int(dur_raw) if dur_raw else DEFAULT_DURATION
            if duration_min <= 0:
                raise ValueError
        except ValueError:
            duration_min = DEFAULT_DURATION

        extra_files = list(cfg_extra_files)
        absolute_candidate = resolve_extra_path(chosen_exe, Path("."))

        if absolute_candidate.is_absolute():
            exe_path = absolute_candidate
            cleanup_base = Path(tempfile.mkdtemp(prefix="discord_quest_"))
            helper_dir = cleanup_base
        else:
            cleanup_base = Path(tempfile.mkdtemp(prefix="discord_quest_"))
            helper_dir = cleanup_base
            exe_path = resolve_exe_path(chosen_exe, cleanup_base)

        if not create_fake_exe(exe_path):
            shutil.rmtree(cleanup_base, ignore_errors=True)
            return

        helper_script = helper_dir / "_quest_helper.pyw"
        signal_file = helper_dir / "_adjust.txt"

        for ef in extra_files:
            if ef["path"]:
                extra_p = resolve_extra_path(ef["path"], helper_dir)
                write_extra_file(extra_p, ef["content"])

        quest_seconds = duration_min * 60
        total_seconds = quest_seconds + DISCORD_DETECT_BUFFER

        game_display_name = app.get("name", exe_path.stem)
        create_quest_window_script(helper_script, game_display_name, total_seconds, signal_file)

        proc = subprocess.Popen(
            [str(exe_path), str(helper_script), str(total_seconds)],
            cwd=str(helper_dir),
        )
        run = QuestRun(
            name=game_display_name,
            exe_name=exe_path.name,
            base_dir=cleanup_base,
            proc=proc,
            quest_seconds=quest_seconds,
            total_seconds=total_seconds,
            started_at=time.monotonic(),
            signal_file=signal_file,
        )
        active_ref.append(run)
        print_ok(f"Quest added via GUI: {game_display_name}")
        do_search()

    tk.Button(btn_frame, text="+ Add Selected Game", command=on_add_selected,
              font=font_normal, bg="#89b4fa", fg="#1e1e2e",
              activebackground="#74c7ec", activeforeground="#1e1e2e",
              relief="flat", padx=12, pady=6, cursor="hand2", bd=0,
              ).pack(side="left", padx=(0, 8))

    def on_stop_all():
        stop_all(active_ref)
        window.destroy()

    tk.Button(btn_frame, text="⏹ Stop All", command=on_stop_all,
              font=font_normal, bg="#f38ba8", fg="#1e1e2e",
              activebackground="#e64553", activeforeground="#1e1e2e",
              relief="flat", padx=12, pady=6, cursor="hand2", bd=0,
              ).pack(side="left", padx=(0, 8))

    def on_close():
        window.destroy()

    tk.Button(btn_frame, text="✕ Close", command=on_close,
              font=font_normal, bg="#45475a", fg="#a6adc8",
              activebackground="#313244", activeforeground="#cdd6f4",
              relief="flat", padx=12, pady=6, cursor="hand2", bd=0,
              ).pack(side="right")

    # ── Bottom info ──
    info_frame = tk.Frame(window, bg="#1e1e2e")
    info_frame.pack(fill="x", padx=16, pady=(0, 8))

    dur_default = tk.StringVar(value=str(DEFAULT_DURATION))
    tk.Label(info_frame, text="Default duration (min):", font=font_small,
             bg="#1e1e2e", fg="#6c7086").pack(side="left")
    dur_entry = tk.Entry(info_frame, textvariable=dur_default, font=font_small,
                         width=6, bg="#45475a", fg="#cdd6f4",
                         insertbackground="#cdd6f4", relief="flat", bd=4, justify="center")
    dur_entry.pack(side="left", padx=(6, 12))

    def on_dur_change():
        global DEFAULT_DURATION
        try:
            v = int(dur_default.get())
            if v > 0:
                DEFAULT_DURATION = v
                print_ok(f"Default duration set to {v} min")
        except ValueError:
            pass

    tk.Button(info_frame, text="Set", command=on_dur_change,
              font=font_small, bg="#45475a", fg="#a6e3a1",
              activebackground="#313244", activeforeground="#a6e3a1",
              relief="flat", padx=10, pady=2, cursor="hand2", bd=0,
              ).pack(side="left")

    tk.Label(info_frame, text="(Press V again or ✕ Close to return to console)",
             font=font_small, bg="#1e1e2e", fg="#585b70").pack(side="right")

    window.protocol("WM_DELETE_WINDOW", on_close)
    window.mainloop()


# ─────────────────────────────────────────────────────────────
# Console UI: main session loop
# ─────────────────────────────────────────────────────────────
def _clear_lines(n: int) -> None:
    """Move cursor up N lines and clear from there to bottom of screen."""
    if n > 0:
        sys.stdout.write(f"\033[{n}A\033[J")
        sys.stdout.flush()


def run_session(apps: list[dict]) -> None:
    active: list[QuestRun] = []
    game_count = len(apps)
    print_session_help()
    print(f"  {DIM}📚 {game_count} games loaded{RESET}")

    _status_lines = 0  # how many lines the last status block occupied

    try:
        while True:
            active = cleanup_finished(active)

            if not active:
                # Clear previous status block if any
                _clear_lines(_status_lines)
                _status_lines = 0
                print()
                print(f"  {DIM}No active quests. Press A to add a game, V for settings GUI, Q to quit.{RESET}")
                while True:
                    key = read_console_key(0.2)
                    if key is None:
                        continue
                    key = key.lower()
                    if key == "a":
                        run = add_quest(apps)
                        if run:
                            active.append(run)
                            print()
                            print_ok("Quest added. Monitoring active quests …")
                        break
                    if key == "q":
                        print_warn("Nothing to stop. Exiting.")
                        return
                    if key == "v":
                        print()
                        print_step("⚙", "Opening settings GUI …")
                        open_settings_gui(apps, active)
                        break
                    if key in ("s", "h", "?"):
                        print_session_help()
                    else:
                        print(f"  {DIM}Press A to add a game, V for settings GUI, Q to quit.{RESET}")
                continue

            # ── Update status in-place ────────────────────────
            _clear_lines(_status_lines)

            print()
            print(f"  {BOLD}Active quests:{RESET}")
            for i, run in enumerate(active, 1):
                print(f"    {render_run(run, i)}")
            print_session_help()
            # Block height: blank line + "Active quests:" + N quest lines + help
            _status_lines = 2 + len(active) + 1

            key = read_console_key(POLL_INTERVAL)

            if key is None:
                continue

            key = key.lower()
            if key == "a":
                run = add_quest(apps)
                _status_lines = 0  # add_quest printed stuff below the status block
                if run:
                    active.append(run)
                    print()
                    print_ok("Quest added. Monitoring active quests …")
            elif key == "s":
                pass  # status was just printed, nothing extra to do
            elif key in ("q", "x"):
                _clear_lines(_status_lines)
                _status_lines = 0
                answer = input(f"  Stop {len(active)} active quest(s) and exit? [y/N]: ").strip().lower()
                if answer in ("y", "yes", "д", "да"):
                    stop_all(active)
                    return
                print_warn("Continuing active quests.")
            elif key == "v":
                print()
                print_step("⚙", "Opening settings GUI …")
                open_settings_gui(apps, active)
                _status_lines = 0  # GUI window interacted with console
            elif key in ("h", "?"):
                pass  # shown in help line already
            else:
                print_warn("Unknown key. Press A to add a game, S for status, or Q to stop all.")

    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}Stopped by user.{RESET}")
        stop_all(active)


# ─────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────
def main():
    print_banner()

    try:
        apps = fetch_detectable()
    except Exception as e:
        print_err(f"Failed to fetch game list: {e}")
        sys.exit(1)

    run_session(apps)


if __name__ == "__main__":
    if sys.platform == "win32":
        os.system("color")
    main()

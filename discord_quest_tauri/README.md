# Discord Quest Completer — Tauri edition

A native desktop re-implementation of `discord_quest.py` built with **Rust + Tauri 2**
and a Discord-like dark UI. The Python CLI remains untouched and fully functional.

## How it works

- The game list is fetched from Discord's public detectable-apps API.
- Starting a quest copies **this app's own binary** into a temp folder under the
  game's executable name (e.g. `exefile.exe`) and launches it with `--quest <json>`.
  The spawned process opens a small quest window with a countdown and ±30s buttons —
  exactly what the Python version's tkinter helper did, but native.
- Discord detects the fake process by name and registers playtime for the quest.

## Development

```bash
cd src-tauri
cargo tauri dev
```

## Building an installer

```bash
cd src-tauri
cargo tauri build
```

Windows: requires the MSVC toolchain + WebView2 (preinstalled on Win10/11).

## Layout

| Path              | Purpose                                    |
|-------------------|--------------------------------------------|
| `src-tauri/src/`  | Rust backend (Discord API, quest manager)  |
| `ui/`             | Vanilla HTML/CSS/JS frontend (no npm)      |
| `scripts/`        | Icon generator (pure Python)               |

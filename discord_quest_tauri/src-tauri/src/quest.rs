use crate::AppState;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, State};

pub const DETECT_BUFFER: i64 = 30;
/// Max session length: 24 h (Game Tier badge needs long sessions).
pub const MAX_MINUTES: i64 = 1440;

#[derive(Serialize, Clone, Debug)]
pub struct QuestInfo {
    pub id: String,
    pub name: String,
    pub exe_name: String,
    pub pid: u32,
    pub remaining: i64,
    pub total_seconds: i64,
    pub status: String, // detecting | running | done | stopped
    pub from_farm: bool,
}

#[derive(Clone, Debug)]
pub struct QuestRun {
    pub id: String,
    pub name: String,
    pub exe_name: String,
    pub pid: u32,
    pub dir: PathBuf,
    pub state_file: PathBuf,
    pub adjust_file: PathBuf,
    pub total_seconds: i64,
    pub done: bool,
    /// Completion/stop already counted toward badge progress.
    pub recorded: bool,
    pub from_farm: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct QuestPayload {
    pub name: String,
    pub total_seconds: i64,
    pub state_file: String,
    pub adjust_file: String,
}

// ── Variety farm (Game Variety badge) ────────────────────────

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct FarmItem {
    pub name: String,
    pub exe_name: String,
}

pub struct FarmState {
    pub queue: Vec<FarmItem>,
    pub index: usize,
    pub minutes_per_game: i64,
    pub current_id: String,
}

#[derive(Serialize, Clone, Debug)]
pub struct FarmStatus {
    pub active: bool,
    pub index: usize,
    pub total: usize,
    pub current: Option<String>,
    pub minutes_per_game: i64,
}

// ── Process helpers ──────────────────────────────────────────

#[cfg(windows)]
fn is_alive(pid: u32) -> bool {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION};
    unsafe {
        let h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if h.is_null() {
            return false;
        }
        CloseHandle(h);
        true
    }
}

#[cfg(not(windows))]
fn is_alive(_pid: u32) -> bool {
    false
}

#[cfg(windows)]
fn kill_pid(pid: u32) {
    let _ = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[cfg(not(windows))]
fn kill_pid(_pid: u32) {}

fn sanitize_exe(raw: &str) -> String {
    let cleaned: String = raw
        .chars()
        .filter(|c| !matches!(c, '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'))
        .collect();
    let cleaned = cleaned.trim();
    if cleaned.is_empty() {
        "game.exe".to_string()
    } else if cleaned.to_lowercase().ends_with(".exe") {
        cleaned.to_string()
    } else {
        format!("{}.exe", cleaned)
    }
}

/// Read the quest window's state. Returns `None` when the file is missing or
/// unparseable (e.g. freshly spawned quest, or mid-write) — callers treat that
/// as "still running" rather than "done" to avoid a false-complete flash.
fn read_state(path: &PathBuf) -> Option<(i64, bool)> {
    let s = fs::read_to_string(path).ok()?;
    let v: serde_json::Value = serde_json::from_str(&s).ok()?;
    let remaining = v.get("remaining").and_then(|x| x.as_i64()).unwrap_or(0);
    let done = v.get("done").and_then(|x| x.as_bool()).unwrap_or(false);
    Some((remaining, done))
}

impl QuestRun {
    fn to_info(&self) -> QuestInfo {
        let (remaining, done) =
            read_state(&self.state_file).unwrap_or((self.total_seconds, false));
        let alive = is_alive(self.pid);
        let status = if done {
            "done".to_string()
        } else if !alive {
            "stopped".to_string()
        } else if remaining > self.total_seconds - DETECT_BUFFER {
            "detecting".to_string()
        } else {
            "running".to_string()
        };
        QuestInfo {
            id: self.id.clone(),
            name: self.name.clone(),
            exe_name: self.exe_name.clone(),
            pid: self.pid,
            remaining: remaining.max(0),
            total_seconds: self.total_seconds,
            status,
            from_farm: self.from_farm,
        }
    }
}

fn cleanup(run: &QuestRun) {
    let _ = fs::remove_dir_all(&run.dir);
}

/// Remove orphaned quest temp dirs from previous sessions (older than 1 day).
/// Quest processes survive the dashboard closing, so their dirs would otherwise
/// accumulate forever.
pub fn sweep_stale_dirs() {
    let Ok(entries) = fs::read_dir(std::env::temp_dir()) else {
        return;
    };
    let cutoff = now_secs() - (24 * 3600) as f64;
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        if !name.starts_with("discord_quest_") {
            continue;
        }
        if let Ok(meta) = entry.metadata() {
            if let Ok(modified) = meta.modified() {
                if let Ok(age) = modified.duration_since(UNIX_EPOCH) {
                    if (age.as_secs() as f64) < cutoff {
                        let _ = fs::remove_dir_all(entry.path());
                    }
                    continue;
                }
            }
        }
        // Unreadable metadata — leave it alone (could be an active quest).
    }
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// Create the fake game executable (a copy of our own binary) and spawn it as a quest window.
/// Returns the tracked `QuestRun`. Shared by the direct-launch command and the variety farm.
fn spawn_quest_inner(
    state: &AppState,
    game_name: String,
    exe_name: String,
    minutes: i64,
    from_farm: bool,
) -> Result<QuestRun, String> {
    let minutes = minutes.clamp(1, MAX_MINUTES);
    let total_seconds = minutes * 60 + DETECT_BUFFER;
    let id = format!(
        "q{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    );
    let dir = std::env::temp_dir().join(format!("discord_quest_{}", id));
    if let Err(e) = fs::create_dir_all(&dir) {
        return Err(e.to_string());
    }
    // Clean up the temp dir on any failure below (mirrors the Python version's
    // shutil.rmtree(base_dir, ignore_errors=True) on error paths).
    let fail = |e: String| {
        let _ = fs::remove_dir_all(&dir);
        e
    };

    let exe_name = sanitize_exe(&exe_name);

    // Copy our own binary (with embedded UI) under the game's executable name.
    let self_exe = std::env::current_exe().map_err(|e| fail(e.to_string()))?;
    let fake_exe = dir.join(&exe_name);
    fs::copy(&self_exe, &fake_exe)
        .map_err(|e| fail(format!("Failed to create {}: {}", exe_name, e)))?;

    let state_file = dir.join("state.json");
    let adjust_file = dir.join("adjust.txt");
    let payload = QuestPayload {
        name: game_name.clone(),
        total_seconds,
        state_file: state_file.to_string_lossy().into_owned(),
        adjust_file: adjust_file.to_string_lossy().into_owned(),
    };
    let payload_json = serde_json::to_string(&payload).map_err(|e| fail(e.to_string()))?;

    let mut cmd = Command::new(&fake_exe);
    cmd.arg("--quest")
        .arg(&payload_json)
        .current_dir(&dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let child = cmd.spawn().map_err(|e| fail(format!("Failed to start quest: {}", e)))?;
    let pid = child.id();

    // Initial state so the dashboard can display progress immediately.
    let _ = fs::write(
        &state_file,
        format!(r#"{{"remaining":{},"done":false}}"#, total_seconds),
    );

    let run = QuestRun {
        id: id.clone(),
        name: game_name,
        exe_name,
        pid,
        dir,
        state_file,
        adjust_file,
        total_seconds,
        done: false,
        recorded: false,
        from_farm,
    };
    state.quests.lock().unwrap().push(run.clone());
    Ok(run)
}

#[tauri::command]
pub fn start_quest(
    state: State<AppState>,
    game_name: String,
    exe_name: String,
    minutes: i64,
) -> Result<QuestInfo, String> {
    let run = spawn_quest_inner(&state, game_name, exe_name, minutes, false)?;
    Ok(run.to_info())
}

#[tauri::command]
pub fn stop_quest(app: AppHandle, state: State<AppState>, id: String) -> Result<(), String> {
    let mut quests = state.quests.lock().unwrap();
    if let Some(run) = quests.iter_mut().find(|q| q.id == id) {
        // Count elapsed playtime BEFORE cleanup wipes state.json, so a quest
        // stopped after N minutes still contributes to Game Tier / Variety.
        if !run.recorded {
            run.recorded = true;
            let (remaining, _) =
                read_state(&run.state_file).unwrap_or((run.total_seconds, false));
            let elapsed_min = (run.total_seconds - remaining).max(0) / 60;
            if elapsed_min > 0 {
                crate::progress::record_completion(&app, &state, &run.name, elapsed_min);
            }
        }
        kill_pid(run.pid);
        run.done = true;
        cleanup(run);
    }
    Ok(())
}

/// Remove a finished quest from the tracker. Attempts cleanup as insurance
/// in case `list_quests` failed to delete the temp dir (e.g. briefly locked exe).
#[tauri::command]
pub fn dismiss_quest(state: State<AppState>, id: String) -> Result<(), String> {
    let mut quests = state.quests.lock().unwrap();
    if let Some(pos) = quests.iter().position(|q| q.id == id) {
        let run = quests.remove(pos);
        cleanup(&run);
    }
    Ok(())
}

#[tauri::command]
pub fn list_quests(app: AppHandle, state: State<AppState>) -> Vec<QuestInfo> {
    // Snapshot the farm's current quest BEFORE locking quests to keep a single
    // lock order (farm → quests) and avoid deadlock with farm_start/farm_advance.
    let farm_current_id =
        state.farm.lock().unwrap().as_ref().map(|f| f.current_id.clone());

    let mut out = Vec::new();
    let mut farm_advance = false;
    let mut farm_current_seen = false;
    {
        let mut quests = state.quests.lock().unwrap();
        let mut i = 0;
        while i < quests.len() {
            let alive = is_alive(quests[i].pid);
            let (remaining, done) =
                read_state(&quests[i].state_file).unwrap_or((quests[i].total_seconds, false));
            quests[i].done = done;
            let status = if done {
                "done".to_string()
            } else if !alive {
                "stopped".to_string()
            } else if remaining > quests[i].total_seconds - DETECT_BUFFER {
                "detecting".to_string()
            } else {
                "running".to_string()
            };

            // Count completed/stopped quests toward badge progress exactly once.
            // Skip zero-minute stops so start/stop spam can't inflate Game Variety.
            if (done || !alive) && !quests[i].recorded {
                quests[i].recorded = true;
                let elapsed_min = (quests[i].total_seconds - remaining).max(0) / 60;
                if elapsed_min > 0 {
                    crate::progress::record_completion(&app, &state, &quests[i].name, elapsed_min);
                }
            }

            // Farm advances when its current quest finished — or vanished
            // (dismissed) — so track both a found-and-finished flag and whether
            // the id was present at all this pass.
            if let Some(cid) = &farm_current_id {
                if &quests[i].id == cid {
                    farm_current_seen = true;
                    if done || !alive {
                        farm_advance = true;
                    }
                }
            }

            if done && alive {
                kill_pid(quests[i].pid);
            }

            // Farm quests auto-dismiss when they finish; manual quests stay
            // until the user dismisses them.
            if quests[i].from_farm && (done || !alive) {
                let _ = fs::remove_dir_all(&quests[i].dir);
                quests.remove(i);
                continue;
            }

            if !alive {
                let _ = fs::remove_dir_all(&quests[i].dir);
            }
            out.push(QuestInfo {
                id: quests[i].id.clone(),
                name: quests[i].name.clone(),
                exe_name: quests[i].exe_name.clone(),
                pid: quests[i].pid,
                remaining: remaining.max(0),
                total_seconds: quests[i].total_seconds,
                status,
                from_farm: quests[i].from_farm,
            });
            i += 1;
        }
    }

    // If the farm's current quest vanished without being seen (e.g. dismissed
    // manually mid-run), treat it as finished so the farm keeps moving.
    if farm_current_id.is_some() && !farm_current_seen {
        farm_advance = true;
    }

    // Farm auto-advance: the current game finished → start the next one.
    if farm_advance {
        let mut farm = state.farm.lock().unwrap();
        if let Some(f) = farm.as_mut() {
            if f.index + 1 < f.queue.len() {
                let next = f.index + 1;
                let item = f.queue[next].clone();
                if let Ok(run) =
                    spawn_quest_inner(&state, item.name, item.exe_name, f.minutes_per_game, true)
                {
                    // Critical: point the farm at the NEW quest so the next poll
                    // knows when to advance again.
                    f.index = next;
                    f.current_id = run.id.clone();
                    // Include the fresh quest in this response so the UI updates
                    // immediately instead of one poll later.
                    out.push(run.to_info());
                }
                // On spawn failure: leave index/current_id untouched so the next
                // poll retries the same game instead of silently skipping it.
            } else {
                *farm = None; // farm finished
            }
        }
    }
    out
}

/// Write a +30 / -30 adjustment for the quest window to pick up.
#[tauri::command]
pub fn adjust_quest(state: State<AppState>, id: String, delta: i64) -> Result<(), String> {
    let quests = state.quests.lock().unwrap();
    if let Some(run) = quests.iter().find(|q| q.id == id) {
        fs::write(&run.adjust_file, delta.to_string()).map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ── Variety farm commands ─────────────────────────────────────

#[tauri::command]
pub fn farm_start(
    state: State<AppState>,
    items: Vec<FarmItem>,
    minutes_per_game: i64,
) -> Result<FarmStatus, String> {
    if items.is_empty() {
        return Err("No games selected".into());
    }
    {
        let farm = state.farm.lock().unwrap();
        if farm.is_some() {
            return Err("A variety farm is already running".into());
        }
    }
    let minutes = minutes_per_game.clamp(1, MAX_MINUTES);
    let first = items[0].clone();
    let run = spawn_quest_inner(&state, first.name, first.exe_name, minutes, true)?;
    *state.farm.lock().unwrap() = Some(FarmState {
        queue: items,
        index: 0,
        minutes_per_game: minutes,
        current_id: run.id,
    });
    Ok(farm_status(state))
}

#[tauri::command]
pub fn farm_stop(app: AppHandle, state: State<AppState>) -> Result<(), String> {
    let current_id = state
        .farm
        .lock()
        .unwrap()
        .as_ref()
        .map(|f| f.current_id.clone());
    if let Some(id) = current_id {
        let _ = stop_quest(app, state.clone(), id);
    }
    *state.farm.lock().unwrap() = None;
    Ok(())
}

#[tauri::command]
pub fn farm_status(state: State<AppState>) -> FarmStatus {
    let farm = state.farm.lock().unwrap();
    match farm.as_ref() {
        Some(f) => FarmStatus {
            active: true,
            index: f.index,
            total: f.queue.len(),
            current: f.queue.get(f.index).map(|i| i.name.clone()),
            minutes_per_game: f.minutes_per_game,
        },
        None => FarmStatus {
            active: false,
            index: 0,
            total: 0,
            current: None,
            minutes_per_game: 0,
        },
    }
}

// ── Quest-window side ─────────────────────────────────────────

#[tauri::command]
pub fn get_quest_payload(state: State<AppState>) -> Option<QuestPayload> {
    state.quest_payload.lock().unwrap().clone()
}

#[tauri::command]
pub fn quest_update_state(
    state: State<AppState>,
    remaining: i64,
    done: bool,
) -> Result<(), String> {
    let payload = state.quest_payload.lock().unwrap().clone();
    if let Some(p) = payload {
        let data = serde_json::json!({ "remaining": remaining, "done": done });
        // Write atomically so the dashboard never reads a half-written file.
        let tmp = format!("{}.tmp", p.state_file);
        fs::write(&tmp, data.to_string()).map_err(|e| e.to_string())?;
        fs::rename(&tmp, &p.state_file).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn quest_get_adjust(state: State<AppState>) -> Result<i64, String> {
    let payload = state.quest_payload.lock().unwrap().clone();
    if let Some(p) = payload {
        if let Ok(s) = fs::read_to_string(&p.adjust_file) {
            let _ = fs::remove_file(&p.adjust_file);
            return s.trim().parse::<i64>().map_err(|e| e.to_string());
        }
    }
    Ok(0)
}

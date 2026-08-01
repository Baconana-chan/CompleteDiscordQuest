use crate::AppState;
use serde::{Deserialize, Serialize};
use std::fs;
use tauri::{AppHandle, Manager, State};

/// Persisted badge progress. The app auto-tracks quest completions, while the
/// user can supply a baseline of what they already had before using the app.
#[derive(Serialize, Deserialize, Clone, Debug, Default)]
#[serde(default)]
pub struct Progress {
    /// Auto-tracked minutes played via quests (Game Tier).
    pub total_minutes: i64,
    /// User-entered baseline minutes already played before this app (Game Tier).
    pub baseline_minutes: i64,
    /// Auto-tracked unique games from quests (Game Variety).
    pub unique_games: Vec<String>,
    /// User-entered games they already played (Game Variety).
    pub manual_games: Vec<String>,
    /// User-entered streaming minutes via Go Live (Streaming badge).
    pub streaming_minutes: i64,
    /// User-entered Discord account creation date, "YYYY-MM-DD" (Account Age).
    pub account_created: Option<String>,
    /// Date Nitro subscription started, "YYYY-MM-DD" (Nitro Subscriber badge).
    pub nitro_since: Option<String>,
    /// Date server boosting started, "YYYY-MM-DD" (Server Boosting badge).
    pub boost_since: Option<String>,
    /// Number of gifts sent (Gifting badge).
    pub gifts: i64,
    /// Completed a Discord quest (Quest badge).
    pub has_quest_badge: bool,
    /// Bought from the Shop for 120 Orbs (Orbs Apprentice badge).
    pub has_orbs_apprentice: bool,
}

/// Editable subset of `Progress` sent from the tracker UI.
#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct ProgressEdit {
    pub baseline_minutes: i64,
    pub manual_games: Vec<String>,
    pub streaming_minutes: i64,
    pub account_created: Option<String>,
    pub nitro_since: Option<String>,
    pub boost_since: Option<String>,
    pub gifts: i64,
    pub has_quest_badge: bool,
    pub has_orbs_apprentice: bool,
}

fn progress_path(app: &AppHandle) -> std::path::PathBuf {
    app.path()
        .app_config_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("discord_quest_progress"))
        .join("progress.json")
}

pub fn load(app: &AppHandle) -> Progress {
    fs::read_to_string(progress_path(app))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save(app: &AppHandle, p: &Progress) {
    if let Some(parent) = progress_path(app).parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(progress_path(app), serde_json::to_string_pretty(p).unwrap_or_default());
}

/// Called when a quest finishes: adds the quest's minutes to the Game Tier
/// counter and records the game for Game Variety (deduplicated).
pub fn record_completion(app: &AppHandle, state: &AppState, name: &str, minutes: i64) {
    let mut p = state.progress.lock().unwrap();
    p.total_minutes += minutes.max(0);
    if !p.unique_games.iter().any(|g| g == name) {
        p.unique_games.push(name.to_string());
    }
    save(app, &p);
}

#[tauri::command]
pub fn get_progress(app: AppHandle, state: State<AppState>) -> Progress {
    let p = load(&app);
    *state.progress.lock().unwrap() = p.clone();
    p
}

/// Save the user-edited baseline data (badge tracker). Auto-tracked fields are
/// preserved — only the supplied baseline fields are replaced.
#[tauri::command]
pub fn update_progress(
    app: AppHandle,
    state: State<AppState>,
    edit: ProgressEdit,
) -> Result<Progress, String> {
    let mut p = state.progress.lock().unwrap();
    p.baseline_minutes = edit.baseline_minutes.max(0);
    p.manual_games = edit.manual_games;
    p.streaming_minutes = edit.streaming_minutes.max(0);
    p.account_created = edit.account_created;
    p.nitro_since = edit.nitro_since;
    p.boost_since = edit.boost_since;
    p.gifts = edit.gifts.max(0);
    p.has_quest_badge = edit.has_quest_badge;
    p.has_orbs_apprentice = edit.has_orbs_apprentice;
    save(&app, &p);
    Ok(p.clone())
}

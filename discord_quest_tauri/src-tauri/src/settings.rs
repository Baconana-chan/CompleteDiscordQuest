use crate::AppState;
use serde::{Deserialize, Serialize};
use std::fs;
use tauri::{AppHandle, Manager, State};

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Settings {
    pub default_minutes: i64,
}

impl Default for Settings {
    fn default() -> Self {
        Self { default_minutes: 15 }
    }
}

fn settings_path(app: &AppHandle) -> std::path::PathBuf {
    app.path()
        .app_config_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("discord_quest_settings"))
        .join("settings.json")
}

pub fn load(app: &AppHandle) -> Settings {
    fs::read_to_string(settings_path(app))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save(app: &AppHandle, s: &Settings) {
    if let Some(parent) = settings_path(app).parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(settings_path(app), serde_json::to_string_pretty(s).unwrap_or_default());
}

#[tauri::command]
pub fn get_settings(app: AppHandle, state: State<AppState>) -> Settings {
    // load() falls back to defaults when no file exists yet.
    let mut guard = state.settings.lock().unwrap();
    *guard = load(&app);
    guard.clone()
}

#[tauri::command]
pub fn set_default_minutes(
    app: AppHandle,
    state: State<AppState>,
    minutes: i64,
) -> Result<(), String> {
    let s = Settings {
        default_minutes: minutes.clamp(1, crate::quest::MAX_MINUTES),
    };
    *state.settings.lock().unwrap() = s.clone();
    save(&app, &s);
    Ok(())
}

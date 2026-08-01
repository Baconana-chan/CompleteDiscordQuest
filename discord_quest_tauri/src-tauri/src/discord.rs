use crate::AppState;
use serde::{Deserialize, Serialize};
use tauri::State;

pub const DISCORD_API: &str = "https://discord.com/api/v10/applications/detectable";

#[derive(Serialize, Clone, Debug)]
pub struct GameInfo {
    pub id: String,
    pub name: String,
    pub executables: Vec<String>,
    pub hook: bool,
}

#[derive(Deserialize, Debug)]
struct RawApp {
    #[serde(default)]
    id: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    executables: Vec<RawExe>,
    #[serde(default)]
    hook: bool,
}

#[derive(Deserialize, Debug)]
struct RawExe {
    #[serde(default)]
    name: String,
    #[serde(default)]
    os: Option<String>,
}

impl From<RawApp> for GameInfo {
    fn from(a: RawApp) -> Self {
        let executables = a
            .executables
            .into_iter()
            .filter(|e| e.os.as_deref().map(|o| o.starts_with("win")).unwrap_or(true))
            .map(|e| e.name)
            .filter(|n| !n.is_empty())
            .collect();
        GameInfo {
            id: a.id,
            name: a.name,
            executables,
            hook: a.hook,
        }
    }
}

/// Fetch the detectable-apps list from the Discord API. Cached in state unless `force`.
#[tauri::command]
pub async fn fetch_games(
    state: State<'_, AppState>,
    force: bool,
) -> Result<Vec<GameInfo>, String> {
    if !force {
        if let Some(games) = state.games.lock().unwrap().clone() {
            return Ok(games);
        }
    }
    let client = reqwest::Client::builder()
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .get(DISCORD_API)
        .timeout(std::time::Duration::from_secs(25))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let raw: Vec<RawApp> = resp.json().await.map_err(|e| e.to_string())?;
    let games: Vec<GameInfo> = raw.into_iter().map(Into::into).collect();
    *state.games.lock().unwrap() = Some(games.clone());
    Ok(games)
}

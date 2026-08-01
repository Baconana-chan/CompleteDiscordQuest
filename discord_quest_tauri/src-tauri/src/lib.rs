mod discord;
mod progress;
mod quest;
mod settings;

use std::sync::Mutex;
use tauri::{WebviewUrl, WebviewWindowBuilder};

pub struct AppState {
    pub games: Mutex<Option<Vec<discord::GameInfo>>>,
    pub quests: Mutex<Vec<quest::QuestRun>>,
    pub settings: Mutex<settings::Settings>,
    /// Badge progress (Game Tier hours + Game Variety unique games), persisted.
    pub progress: Mutex<progress::Progress>,
    /// Variety farm (auto-cycle through games), present while active.
    pub farm: Mutex<Option<quest::FarmState>>,
    /// Present only when the process was launched as a quest window (`--quest <json>`).
    pub quest_payload: Mutex<Option<quest::QuestPayload>>,
}

pub fn run() {
    let args: Vec<String> = std::env::args().collect();
    // Only the dashboard sweeps; quest-window processes must not delete their
    // own live temp dir.
    if !args.iter().any(|a| a == "--quest") {
        quest::sweep_stale_dirs();
    }
    let quest_payload: Option<quest::QuestPayload> = args
        .iter()
        .position(|a| a == "--quest")
        .and_then(|i| args.get(i + 1))
        .and_then(|s| serde_json::from_str(s).ok());

    tauri::Builder::default()
        .manage(AppState {
            games: Mutex::new(None),
            quests: Mutex::new(Vec::new()),
            settings: Mutex::new(settings::Settings::default()),
            progress: Mutex::new(progress::Progress::default()),
            farm: Mutex::new(None),
            quest_payload: Mutex::new(quest_payload.clone()),
        })
        .invoke_handler(tauri::generate_handler![
            discord::fetch_games,
            quest::start_quest,
            quest::stop_quest,
            quest::dismiss_quest,
            quest::list_quests,
            quest::adjust_quest,
            quest::get_quest_payload,
            quest::quest_update_state,
            quest::quest_get_adjust,
            quest::farm_start,
            quest::farm_stop,
            quest::farm_status,
            progress::get_progress,
            progress::update_progress,
            settings::get_settings,
            settings::set_default_minutes,
        ])
        .setup(move |app| {
            if let Some(payload) = quest_payload {
                // Quest window mode: the copied fake exe runs as this process.
                let win = WebviewWindowBuilder::new(
                    app,
                    "quest",
                    WebviewUrl::App("index.html".into()),
                )
                .title(format!("{} — Quest", payload.name))
                .inner_size(430.0, 300.0)
                .resizable(false)
                .center()
                .build()?;
                win.show()?;
            } else {
                let win = WebviewWindowBuilder::new(
                    app,
                    "main",
                    WebviewUrl::App("index.html".into()),
                )
                .title("Discord Quest Completer")
                .inner_size(1080.0, 720.0)
                .min_inner_size(920.0, 600.0)
                .center()
                .build()?;
                win.show()?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/* Discord Quest Completer — frontend */
const { invoke } = window.__TAURI__.core;
const { getCurrentWindow } = window.__TAURI__.window;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

let games = [];
let quests = [];
let view = "quests";
let searchTimer = null;
let pollTimer = null;
let selectedGame = null;
let settings = { default_minutes: 15 };
let questsDomKey = "";
let progress = {
  total_minutes: 0, baseline_minutes: 0,
  unique_games: [], manual_games: [],
  streaming_minutes: 0, account_created: null,
  nitro_since: null, boost_since: null,
  gifts: 0, has_quest_badge: false, has_orbs_apprentice: false,
};
let farm = null;
let farmQueue = [];

/* ── helpers ─────────────────────────────────────────── */
function fmt(s) {
  s = Math.max(0, Math.round(s));
  const m = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${m}:${ss}`;
}

/* Human-readable duration: 1h 23m for long sessions, else mm:ss */
function fmtH(s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return fmt(s);
}

/* Badge level helpers */
const TIER_LEVELS = [1, 5, 20, 75, 150, 300, 500, 1000, 2000, 5000];
const VARIETY_LEVELS = [2, 5, 10, 15, 20, 30, 40, 60, 80, 100];
/* Account Age (months): 10 levels — level 1 = 1 year, up to 10 years */
const ACCOUNT_LEVELS = [12, 24, 36, 48, 60, 72, 84, 96, 108, 120];
/* Nitro Subscriber (months): Bronze → Opal, 8 levels */
const NITRO_LEVELS = [1, 3, 6, 12, 24, 36, 60, 72];
const NITRO_NAMES = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Emerald", "Ruby", "Opal"];
/* Server Boosting (months): 8 levels */
const BOOST_LEVELS = [1, 2, 3, 6, 9, 12, 18, 24];
/* Gifting (gifts sent): Patron → Legend, 6 levels */
const GIFT_LEVELS = [1, 2, 3, 6, 10, 20];
const GIFT_NAMES = ["Patron", "Champion", "Luminary", "Icon", "Hero", "Legend"];

function fmtMonths(m) {
  if (m >= 12) {
    const y = Math.floor(m / 12);
    const r = m % 12;
    return r ? `${y} yr ${r} mo` : `${y} yr`;
  }
  return `${m} mo`;
}

function badgeLevel(value, levels) {
  let lvl = 0;
  for (const l of levels) if (value >= l) lvl++;
  return Math.min(lvl, levels.length);
}

function badgeProgress(value, levels) {
  const lvl = badgeLevel(value, levels);
  if (lvl >= levels.length) return 100;
  const cur = lvl === 0 ? 0 : levels[lvl - 1];
  const next = levels[lvl];
  return Math.min(100, Math.round(((value - cur) / (next - cur)) * 100));
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function debounce(fn, ms) {
  return (...args) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => fn(...args), ms);
  };
}

/* ── boot ────────────────────────────────────────────── */
async function boot() {
  let payload = null;
  try {
    payload = await invoke("get_quest_payload");
  } catch (e) { /* main mode */ }
  if (payload) {
    initQuestWindow(payload);
  } else {
    initMain();
  }
}

/* ── Quest window mode (fake exe process) ────────────── */
async function initQuestWindow(payload) {
  $("#quest-mode").classList.remove("hidden");
  document.title = `${payload.name} — Quest`;
  $("#qw-title").textContent = payload.name;

  let total = payload.total_seconds;
  let base = Date.now();
  let done = false;

  const render = () => {
    const elapsed = Math.max(0, Math.floor((Date.now() - base) / 1000));
    const remaining = Math.max(0, total - elapsed);
    const pct = total > 0 ? Math.min(100, ((total - elapsed) / total) * 100) : 0;
    $("#qw-fill").style.width = pct + "%";
    $("#qw-time").textContent = fmtH(remaining);
    const buf = total - remaining;
    $("#qw-status").textContent = done
      ? "Quest complete! You may close this window."
      : buf < 30
        ? "Waiting for Discord to detect the process…"
        : "Quest in progress";
  };

  const tick = async () => {
    if (done) return;
    // Pick up adjustments requested from the main app (+30s / -30s).
    let adj = 0;
    try { adj = await invoke("quest_get_adjust"); } catch (e) {}
    if (adj) {
      if (adj > 0 || total - Math.floor((Date.now() - base) / 1000) > 35) {
        total += adj;
      }
    }
    const remaining = total - Math.floor((Date.now() - base) / 1000);
    if (remaining <= 0) {
      done = true;
      try {
        await invoke("quest_update_state", { remaining: 0, done: true });
      } catch (e) {}
      render();
      setTimeout(() => {
        try { getCurrentWindow().close(); } catch (e) {}
      }, 4000);
      return;
    }
    try {
      await invoke("quest_update_state", { remaining, done: false });
    } catch (e) {}
    render();
  };

  $("#qw-plus").onclick = () => { if (!done) { total += 30; render(); } };
  $("#qw-minus").onclick = () => {
    if (!done && total - Math.floor((Date.now() - base) / 1000) > 35) {
      total -= 30;
      render();
    }
  };

  render();
  setInterval(tick, 1000);
}

/* ── Main app ────────────────────────────────────────── */
async function initMain() {
  $("#app").classList.remove("hidden");
  bindNav();
  bindModal();
  bindTopbar();

  // Settings
  try {
    settings = await invoke("get_settings");
    $("#aq-minutes").value = settings.default_minutes || 15;
  } catch (e) {}

  // Load games
  renderView("quests");
  loadGames();

  pollTimer = setInterval(poll, 1000);
  poll();
}

async function loadGames() {
  const lib = $("#view-library");
  lib.innerHTML = `<div class="loading"><div class="spinner"></div> Fetching game list from Discord API…</div>`;
  try {
    games = await invoke("fetch_games", { force: false });
    $("#game-count").textContent = games.length.toLocaleString();
    if (view === "library") renderLibrary("");
  } catch (e) {
    lib.innerHTML = `<div class="empty"><div class="empty-icon">😢</div><div class="empty-title">Failed to load games</div><div class="empty-sub">${esc(e)}</div></div>`;
  }
}

/* ── navigation ──────────────────────────────────────── */
function bindNav() {
  $$(".rail-item").forEach((btn) => {
    btn.addEventListener("click", () => renderView(btn.dataset.view));
  });
  $$(".side-item").forEach((btn) => {
    btn.addEventListener("click", () => renderView(btn.dataset.view));
  });
  $("#global-search").addEventListener("input", debounce((e) => {
    if (view === "quests") {
      renderView("library");
      const libSearch = $("#lib-search");
      if (libSearch) {
        libSearch.value = e.target.value;
        renderLibrary(e.target.value);
      }
    }
  }, 250));
}

function renderView(v) {
  view = v;
  $$(".rail-item").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("#view-quests").classList.toggle("hidden", v !== "quests");
  $("#view-library").classList.toggle("hidden", v !== "library");
  $("#view-badges").classList.toggle("hidden", v !== "badges");
  $("#view-settings").classList.toggle("hidden", v !== "settings");
  const titles = { quests: "quests", library: "library", badges: "badges", settings: "settings" };
  $("#topbar-title").textContent = titles[v];
  if (v === "quests") renderQuests();
  if (v === "library") renderLibrary("");
  if (v === "badges") renderBadges();
  if (v === "settings") renderSettings();
}

/* ── quests view ─────────────────────────────────────── */
async function poll() {
  try {
    quests = await invoke("list_quests");
  } catch (e) { return; }
  try {
    farm = await invoke("farm_status");
  } catch (e) {}
  if (view === "quests") renderQuests();
  if (view === "badges") updateFarmStatus();
  renderSideQuests();
}

function farmBanner() {
  if (!farm || !farm.active) return "";
  return `
    <div class="farm-banner">
      <div class="farm-banner-icon">🌾</div>
      <div class="farm-banner-body">
        <div class="farm-banner-title">Variety Farm · Game ${farm.index + 1} of ${farm.total}</div>
        <div class="farm-banner-sub">${esc(farm.current || "")} · ${farm.minutes_per_game} min per game</div>
      </div>
      <button class="btn danger sm" id="farm-banner-stop">Stop</button>
    </div>`;
}

function renderQuests() {
  const wrap = $("#view-quests");
  if (!quests.length) {
    questsDomKey = "";
    wrap.innerHTML = `
      ${farmBanner()}
      <div class="empty">
        <div class="empty-icon">🎮</div>
        <div class="empty-title">No active quests</div>
        <div class="empty-sub">Add a game and run its fake executable so Discord registers your playtime.</div>
        <button class="btn brand" data-add>＋ Add Quest</button>
      </div>`;
    const addBtn = wrap.querySelector("[data-add]");
    if (addBtn) addBtn.addEventListener("click", openModal);
    bindFarmBanner();
    return;
  }
  // Only rebuild the DOM when the quest set or statuses change; otherwise
  // update progress bars and timers in place so CSS transitions and hover
  // states survive between ticks.
  const key = quests.map((q) => `${q.id}:${q.status}`).join("|");
  if (key !== questsDomKey) {
    questsDomKey = key;
    wrap.innerHTML = `${farmBanner()}<div class="quests-grid">${quests.map(questCard).join("")}</div>`;
    bindFarmBanner();
    $$(".qc-btns button").forEach((b) => {
      b.addEventListener("click", () => onQuestAction(b.dataset));
    });
    $$(".qc-dismiss").forEach((b) => {
      b.addEventListener("click", () => onQuestDismiss(b.dataset.id));
    });
    return;
  }
  // In-place update: bar width + time label only.
  quests.forEach((q) => {
    const card = wrap.querySelector(`[data-id="${CSS.escape(q.id)}"]`);
    if (!card) return;
    const fill = card.querySelector(".qc-fill");
    const pct = q.total_seconds > 0
      ? Math.min(100, Math.max(0, ((q.total_seconds - q.remaining) / q.total_seconds) * 100))
      : 0;
    if (fill) fill.style.width = pct + "%";
    const timeEl = card.querySelector(".qc-time");
    if (timeEl) {
      timeEl.textContent = q.status === "done" ? "Complete" : q.status === "stopped" ? "Stopped early" : fmtH(q.remaining) + " left";
    }
  });
}

function bindFarmBanner() {
  const stop = $("#farm-banner-stop");
  if (stop) stop.addEventListener("click", stopFarm);
}

function questCard(q) {
  const pct = q.total_seconds > 0
    ? Math.min(100, Math.max(0, ((q.total_seconds - q.remaining) / q.total_seconds) * 100))
    : 0;
  const pillCls = { detecting: "pill-detect", running: "pill-run", done: "pill-done", stopped: "pill-stopped" }[q.status];
  const label = { detecting: "Detecting", running: "Running", done: "Done", stopped: "Stopped" }[q.status];
  const showBtns = q.status === "running" || q.status === "detecting";
  const fillCls = q.status === "done" ? "done-fill" : q.status === "detecting" ? "pulse" : "";
  return `
    <div class="quest-card" data-id="${esc(q.id)}">
      <div class="qc-head">
        <div class="qc-icon">🎮</div>
        <div>
          <div class="qc-title">${esc(q.name)}</div>
          <div class="qc-exe">${esc(q.exe_name)}</div>
        </div>
        <span class="qc-pills">
          ${q.from_farm ? `<span class="qc-pill pill-farm">🌾 Farm</span>` : ""}
          <span class="qc-pill ${pillCls}">${label}</span>
        </span>
      </div>
      <div class="qc-progress"><div class="qc-fill ${fillCls}" style="width:${pct}%"></div></div>
      <div class="qc-meta">
        <span>PID ${q.pid}</span>
        <span class="qc-time">${q.status === "done" ? "Complete" : q.status === "stopped" ? "Stopped early" : fmtH(q.remaining) + " left"}</span>
      </div>
      <div class="qc-btns">
        ${showBtns
          ? `<button class="btn ghost sm" data-action="minus" data-id="${esc(q.id)}">−30s</button>
             <button class="btn ghost sm" data-action="plus" data-id="${esc(q.id)}">+30s</button>
             <button class="btn danger sm" data-action="stop" data-id="${esc(q.id)}" style="margin-left:auto">Stop</button>`
          : `<button class="btn ghost sm qc-dismiss" data-id="${esc(q.id)}" style="margin-left:auto">Dismiss</button>`}
      </div>
    </div>`;
}

async function onQuestAction({ action, id }) {
  if (action === "stop") {
    try {
      await invoke("stop_quest", { id });
      toast("Quest stopped");
    } catch (e) { toast(e, "error"); }
  } else {
    const delta = action === "plus" ? 30 : -30;
    try {
      await invoke("adjust_quest", { id, delta });
    } catch (e) { toast(e, "error"); }
  }
}

async function onQuestDismiss(id) {
  try {
    await invoke("dismiss_quest", { id });
  } catch (e) { toast(e, "error"); }
}

function renderSideQuests() {
  const el = $("#side-quests");
  const active = quests.filter((q) => q.status === "running" || q.status === "detecting");
  if (!active.length) {
    el.innerHTML = `<div class="side-quest" style="color:var(--text-faint)">No active quests</div>`;
    return;
  }
  el.innerHTML = active.map((q) => `
    <div class="side-quest" title="${esc(q.name)}">
      <span class="mini-dot ${q.status}"></span>
      <span>${esc(q.name)}</span>
    </div>`).join("");
}

/* ── badges view ─────────────────────────────────────── */
async function renderBadges() {
  try {
    progress = await invoke("get_progress");
  } catch (e) {}
  try {
    farm = await invoke("farm_status");
  } catch (e) {}
  const tierHours = (progress.total_minutes + progress.baseline_minutes) / 60;
  const tierLvl = badgeLevel(tierHours, TIER_LEVELS);
  const tierPct = badgeProgress(tierHours, TIER_LEVELS);
  const allGames = [...new Set([...progress.unique_games, ...progress.manual_games])];
  const varCount = allGames.length;
  const varLvl = badgeLevel(varCount, VARIETY_LEVELS);
  const varPct = badgeProgress(varCount, VARIETY_LEVELS);
  const streamHours = progress.streaming_minutes / 60;
  const streamLvl = badgeLevel(streamHours, TIER_LEVELS);
  const streamPct = badgeProgress(streamHours, TIER_LEVELS);
  const ageMonths = monthsSince(progress.account_created);
  const ageLvl = ageMonths === null ? 0 : badgeLevel(ageMonths, ACCOUNT_LEVELS);
  const ageMax = ACCOUNT_LEVELS.length;
  const agePct = ageMonths === null ? 0 : badgeProgress(ageMonths, ACCOUNT_LEVELS);
  const nitroMonths = monthsSince(progress.nitro_since);
  const nitroLvl = nitroMonths === null ? 0 : badgeLevel(nitroMonths, NITRO_LEVELS);
  const nitroMax = NITRO_LEVELS.length;
  const nitroPct = nitroMonths === null ? 0 : badgeProgress(nitroMonths, NITRO_LEVELS);
  const boostMonths = monthsSince(progress.boost_since);
  const boostLvl = boostMonths === null ? 0 : badgeLevel(boostMonths, BOOST_LEVELS);
  const boostMax = BOOST_LEVELS.length;
  const boostPct = boostMonths === null ? 0 : badgeProgress(boostMonths, BOOST_LEVELS);
  const giftLvl = badgeLevel(progress.gifts, GIFT_LEVELS);
  const giftMax = GIFT_LEVELS.length;
  const giftPct = badgeProgress(progress.gifts, GIFT_LEVELS);
  const wrap = $("#view-badges");
  wrap.innerHTML = `
    <div class="badges-grid">
      ${badgeCard("⏱️", "Game Tier", "Time played in games", tierLvl, 10, tierPct,
        `${tierHours.toFixed(1)} h total`, tierLvl >= 10 ? "Max level reached!" : `Next level: ${TIER_LEVELS[tierLvl]} h`)}
      ${badgeCard("🎮", "Game Variety", "Unique games played", varLvl, 10, varPct,
        `${varCount} unique game${varCount === 1 ? "" : "s"}`, varLvl >= 10 ? "Max level reached!" : `Next level: ${VARIETY_LEVELS[varLvl]} games`)}
      ${badgeCard("📡", "Streaming", "Go Live in a voice channel", streamLvl, 10, streamPct,
        `${streamHours.toFixed(1)} h streamed`, streamLvl >= 10 ? "Max level reached!" : `Next level: ${TIER_LEVELS[streamLvl]} h`,
        "The fake process can't count as a stream. 💡 Synergy: run a quest and share its window via Go Live to grind Game Tier + Streaming at once.")}
      ${badgeCard("🗓️", "Account Age", "Account creation date", ageLvl, ageMax, agePct,
        ageMonths === null ? "Unknown" : `${(ageMonths / 12).toFixed(1)} yr old`,
        ageLvl >= ageMax ? "Max level reached!" : `Next level at ${ACCOUNT_LEVELS[ageLvl] / 12} yr`)}
      ${badgeCard("💎", "Nitro Subscriber", "Nitro subscription length", nitroLvl, nitroMax, nitroPct,
        nitroMonths === null ? "Unknown" : fmtMonths(nitroMonths),
        nitroLvl >= nitroMax ? "Max level reached!" : `Next: ${NITRO_NAMES[nitroLvl]} (${fmtMonths(NITRO_LEVELS[nitroLvl])})`)}
      ${badgeCard("🚀", "Server Boosting", "Time boosting servers", boostLvl, boostMax, boostPct,
        boostMonths === null ? "Unknown" : fmtMonths(boostMonths),
        boostLvl >= boostMax ? "Max level reached!" : `Next: ${fmtMonths(BOOST_LEVELS[boostLvl])} of boosting`)}
      ${badgeCard("🎁", "Gifting", "Gifts sent", giftLvl, giftMax, giftPct,
        `${progress.gifts} gift${progress.gifts === 1 ? "" : "s"} sent`,
        giftLvl >= giftMax ? "Max level reached!" : `Next: ${GIFT_NAMES[giftLvl]} (${GIFT_LEVELS[giftLvl]} gift${GIFT_LEVELS[giftLvl] === 1 ? "" : "s"})`)}
      ${badgeCard("🎯", "Quest", "Completed a Discord quest",
        progress.has_quest_badge ? 1 : 0, 1, progress.has_quest_badge ? 100 : 0,
        progress.has_quest_badge ? "Owned!" : "Not owned",
        "",
        "Complete a sponsored task (e.g. stream a game in a voice channel) to earn it.")}
      ${badgeCard("🔮", "Orbs Apprentice", "Bought from the Shop",
        progress.has_orbs_apprentice ? 1 : 0, 1, progress.has_orbs_apprentice ? 100 : 0,
        progress.has_orbs_apprentice ? "Owned!" : "Not owned",
        "",
        "Purchasable from the Shop for 120 Orbs.")}
    </div>
    ${trackerPanel()}
    <div class="farm-panel">
      <div class="farm-panel-head">
        <h2>🌾 Variety Farm</h2>
        <span class="farm-panel-sub">Auto-cycles through games to grind the Game Variety badge</span>
      </div>
      <div class="farm-panel-body">
        <div class="farm-search-row">
          <input id="farm-search" class="input" placeholder="Search games to queue…" autocomplete="off" />
          <div id="farm-results" class="farm-results"></div>
        </div>
        <div id="farm-queue" class="farm-queue"></div>
        <div class="farm-controls">
          <label class="farm-label">Minutes per game</label>
          <input id="farm-minutes" class="input dur" type="number" value="2" min="1" max="60" />
          <button class="btn brand" id="farm-start">▶ Start Farm</button>
          <button class="btn danger hidden" id="farm-stop">■ Stop Farm</button>
          <div id="farm-status" class="farm-status-text"></div>
        </div>
      </div>
    </div>`;
  bindFarm();
  bindTracker();
}

function badgeCard(icon, name, sub, lvl, maxLvl, pct, stat, next, note = "") {
  return `
    <div class="badge-card">
      <div class="badge-card-head">
        <div class="badge-icon">${icon}</div>
        <div class="badge-card-titles">
          <div class="badge-name">${name}</div>
          <div class="badge-sub">${sub}</div>
        </div>
        <div class="badge-level">${maxLvl === 1 ? (lvl >= 1 ? "✓ Owned" : "✗ Not owned") : `Lv ${lvl}<span class="badge-level-max">/${maxLvl}</span>`}</div>
      </div>
      <div class="badge-stat">${stat}</div>
      <div class="badge-bar"><div class="badge-fill" style="width:${pct}%"></div></div>
      ${next ? `<div class="badge-next">${next}</div>` : ""}
      ${note ? `<p class="badge-note">${note}</p>` : ""}
    </div>`;
}

/* ── badge tracker (edit your own data) ───────────────── */
/* Full months elapsed since a date — used by Account Age, Nitro Subscriber,
   and Server Boosting. If today's day is before the start day, the
   anniversary hasn't passed yet — don't overstate the level. */
function monthsSince(iso) {
  if (!iso) return null;
  const created = new Date(iso + "T00:00:00");
  if (isNaN(created)) return null;
  const now = new Date();
  let months = (now.getFullYear() - created.getFullYear()) * 12 +
    (now.getMonth() - created.getMonth());
  if (now.getDate() < created.getDate()) months -= 1;
  return Math.max(0, months);
}

function trackerPanel() {
  return `
    <div class="farm-panel tracker-panel">
      <div class="farm-panel-head">
        <h2>📝 Badge Tracker</h2>
        <span class="farm-panel-sub">Tell the app what you already had before using it — auto-tracked quest data is added on top.</span>
      </div>
      <div class="tracker-grid">
        <div class="tracker-row">
          <div class="tracker-label">⏱️ Game Tier baseline<span class="tracker-desc">Hours already played before this app</span></div>
          <div class="tracker-inputs">
            <input id="tr-tier-hours" class="input dur" type="number" min="0" step="0.5" value="${(progress.baseline_minutes / 60).toFixed(1)}" />
            <button class="btn ghost sm" data-save="tier">Save</button>
          </div>
        </div>
        <div class="tracker-row">
          <div class="tracker-label">🎮 Games already played<span class="tracker-desc">Search the library and add games you've played before</span></div>
          <div class="tracker-games">
            <div class="tracker-search-row">
              <input id="tr-search" class="input" placeholder="Search games…" autocomplete="off" />
              <div id="tr-results" class="farm-results"></div>
            </div>
            <div id="tr-games" class="farm-queue"></div>
          </div>
        </div>
        <div class="tracker-row">
          <div class="tracker-label">📡 Streaming baseline<span class="tracker-desc">Hours already streamed via Go Live</span></div>
          <div class="tracker-inputs">
            <input id="tr-stream-hours" class="input dur" type="number" min="0" step="0.5" value="${(progress.streaming_minutes / 60).toFixed(1)}" />
            <button class="btn ghost sm" data-save="stream">Save</button>
          </div>
        </div>
        <div class="tracker-row">
          <div class="tracker-label">🗓️ Account created<span class="tracker-desc">Your Discord account creation date</span></div>
          <div class="tracker-inputs">
            <input id="tr-account-date" class="input" type="date" value="${esc(progress.account_created || "")}" />
            <button class="btn ghost sm" data-save="account">Save</button>
          </div>
        </div>
        <div class="tracker-row">
          <div class="tracker-label">💎 Nitro since<span class="tracker-desc">When your Nitro subscription started</span></div>
          <div class="tracker-inputs">
            <input id="tr-nitro-date" class="input" type="date" value="${esc(progress.nitro_since || "")}" />
            <button class="btn ghost sm" data-save="nitro">Save</button>
          </div>
        </div>
        <div class="tracker-row">
          <div class="tracker-label">🚀 Boosting since<span class="tracker-desc">When you started boosting servers</span></div>
          <div class="tracker-inputs">
            <input id="tr-boost-date" class="input" type="date" value="${esc(progress.boost_since || "")}" />
            <button class="btn ghost sm" data-save="boost">Save</button>
          </div>
        </div>
        <div class="tracker-row">
          <div class="tracker-label">🎁 Gifts sent<span class="tracker-desc">Total Nitro gifts you've sent</span></div>
          <div class="tracker-inputs">
            <input id="tr-gifts" class="input dur" type="number" min="0" step="1" value="${progress.gifts}" />
            <button class="btn ghost sm" data-save="gifts">Save</button>
          </div>
        </div>
        <div class="tracker-row">
          <div class="tracker-label">🎯 Quest badge<span class="tracker-desc">Completed a Discord quest</span></div>
          <div class="tracker-inputs">
            <label class="switch"><input type="checkbox" id="tr-quest" ${progress.has_quest_badge ? "checked" : ""} /><span class="switch-slider"></span></label>
            <button class="btn ghost sm" data-save="quest">Save</button>
          </div>
        </div>
        <div class="tracker-row">
          <div class="tracker-label">🔮 Orbs Apprentice<span class="tracker-desc">Bought from the Shop for 120 Orbs</span></div>
          <div class="tracker-inputs">
            <label class="switch"><input type="checkbox" id="tr-orbs" ${progress.has_orbs_apprentice ? "checked" : ""} /><span class="switch-slider"></span></label>
            <button class="btn ghost sm" data-save="orbs">Save</button>
          </div>
        </div>
      </div>
    </div>`;
}

function bindTracker() {
  $$("[data-save]").forEach((btn) => {
    btn.addEventListener("click", () => saveTracker(btn.dataset.save));
  });
  const search = $("#tr-search");
  if (search) {
    search.addEventListener("input", debounce((e) => renderTrackerResults(e.target.value), 200));
  }
  renderTrackerGames();
}

function renderTrackerResults(q) {
  const wrap = $("#tr-results");
  const query = (q || "").trim().toLowerCase();
  if (!query) { wrap.innerHTML = ""; return; }
  const already = new Set([...progress.unique_games, ...progress.manual_games]);
  const matches = games
    .filter((g) => g.name.toLowerCase().includes(query) && !already.has(g.name))
    .slice(0, 8);
  if (!matches.length) {
    wrap.innerHTML = `<div class="warn">No new games found.</div>`;
    return;
  }
  wrap.innerHTML = matches.map((g) => `
    <button class="farm-result" data-name="${esc(g.name)}">
      <span>🎮</span>
      <span class="farm-result-name">${esc(g.name)}</span>
      <span class="exe-badge">＋</span>
    </button>`).join("");
  $$(".farm-result").forEach((row) => {
    row.addEventListener("click", async () => {
      progress.manual_games.push(row.dataset.name);
      $("#tr-search").value = "";
      $("#tr-results").innerHTML = "";
      renderTrackerGames();
      await saveTracker("games");
    });
  });
}

function renderTrackerGames() {
  const wrap = $("#tr-games");
  if (!wrap) return;
  if (!progress.manual_games.length) {
    wrap.innerHTML = `<div class="farm-empty">No manually-added games yet.</div>`;
    return;
  }
  wrap.innerHTML = progress.manual_games.map((g, i) => `
    <span class="farm-chip">🎮 ${esc(g)} <button class="farm-chip-x" data-i="${i}" title="Remove">✕</button></span>
  `).join("");
  $$(".farm-chip-x").forEach((btn) => {
    btn.addEventListener("click", async () => {
      progress.manual_games.splice(parseInt(btn.dataset.i, 10), 1);
      renderTrackerGames();
      await saveTracker("games");
    });
  });
}

/* Parse a live hours-input into minutes; fall back to saved value when the
   field is empty/invalid so an unrelated save never zeroes typed data. */
function liveHoursToMinutes(sel, fallback) {
  const el = $(sel);
  if (!el || el.value.trim() === "") return fallback;
  const v = Number(el.value);
  return Number.isFinite(v) ? Math.round(v * 60) : fallback;
}

async function saveTracker(field) {
  // Tauri converts camelCase→snake_case only for top-level command args, NOT
  // for fields inside a struct — so use exact snake_case keys here (same as
  // farmQueue uses `exe_name`).
  // Read live tier/stream inputs so typed-but-unsaved values survive when the
  // save is triggered from another row (e.g. adding a game or toggling a switch).
  const edit = {
    baseline_minutes: liveHoursToMinutes("#tr-tier-hours", progress.baseline_minutes),
    manual_games: progress.manual_games,
    streaming_minutes: liveHoursToMinutes("#tr-stream-hours", progress.streaming_minutes),
    account_created: progress.account_created,
    nitro_since: progress.nitro_since,
    boost_since: progress.boost_since,
    gifts: progress.gifts,
    has_quest_badge: progress.has_quest_badge,
    has_orbs_apprentice: progress.has_orbs_apprentice,
  };
  if (field === "tier") {
    edit.baseline_minutes = liveHoursToMinutes("#tr-tier-hours", progress.baseline_minutes);
  } else if (field === "stream") {
    edit.streaming_minutes = liveHoursToMinutes("#tr-stream-hours", progress.streaming_minutes);
  } else if (field === "account") {
    edit.account_created = $("#tr-account-date").value || null;
  } else if (field === "nitro") {
    edit.nitro_since = $("#tr-nitro-date").value || null;
  } else if (field === "boost") {
    edit.boost_since = $("#tr-boost-date").value || null;
  } else if (field === "gifts") {
    edit.gifts = parseInt($("#tr-gifts").value, 10) || 0;
  } else if (field === "quest") {
    edit.has_quest_badge = $("#tr-quest").checked;
  } else if (field === "orbs") {
    edit.has_orbs_apprentice = $("#tr-orbs").checked;
  }
  try {
    progress = await invoke("update_progress", { edit });
    if (field !== "games") toast("Badge tracker saved", "success");
    renderBadges();
  } catch (e) {
    toast(e, "error");
  }
}

function bindFarm() {
  const search = $("#farm-search");
  search.addEventListener("input", debounce((e) => renderFarmResults(e.target.value), 200));
  const start = $("#farm-start");
  const stop = $("#farm-stop");
  start.addEventListener("click", startFarm);
  stop.addEventListener("click", stopFarm);
  renderFarmQueue();
  updateFarmStatus();
}

function renderFarmResults(q) {
  const wrap = $("#farm-results");
  const query = (q || "").trim().toLowerCase();
  if (!query) {
    wrap.innerHTML = "";
    return;
  }
  const matches = games
    .filter((g) => g.executables.length && g.name.toLowerCase().includes(query))
    .slice(0, 8);
  if (!matches.length) {
    wrap.innerHTML = `<div class="warn">No games with executables found.</div>`;
    return;
  }
  wrap.innerHTML = matches.map((g) => `
    <button class="farm-result" data-id="${esc(g.id)}">
      <span>🎮</span>
      <span class="farm-result-name">${esc(g.name)}</span>
      <span class="exe-badge">${esc(g.executables[0])}</span>
    </button>`).join("");
  $$(".farm-result").forEach((row) => {
    row.addEventListener("click", () => {
      const g = games.find((x) => x.id === row.dataset.id);
      if (!g) return;
      if (farmQueue.some((fq) => fq.name === g.name)) {
        toast("Already queued", "warn");
        return;
      }
      farmQueue.push({ name: g.name, exe_name: g.executables[0] });
      renderFarmQueue();
    });
  });
}

function renderFarmQueue() {
  const wrap = $("#farm-queue");
  if (!farmQueue.length) {
    wrap.innerHTML = `<div class="farm-empty">No games queued — search above and click to add.</div>`;
    return;
  }
  wrap.innerHTML = farmQueue.map((g, i) => `
    <span class="farm-chip">🎮 ${esc(g.name)} <button class="farm-chip-x" data-i="${i}" title="Remove">✕</button></span>
  `).join("");
  $$(".farm-chip-x").forEach((btn) => {
    btn.addEventListener("click", () => {
      farmQueue.splice(parseInt(btn.dataset.i, 10), 1);
      renderFarmQueue();
    });
  });
}

async function startFarm() {
  if (!farmQueue.length) {
    toast("Queue at least one game first", "error");
    return;
  }
  const minutes = parseInt($("#farm-minutes").value, 10) || 2;
  try {
    farm = await invoke("farm_start", { items: farmQueue, minutesPerGame: minutes });
    farmQueue = [];
    toast(`Farm started: ${farm.total} games × ${minutes} min`, "success");
    renderFarmQueue();
    updateFarmStatus();
  } catch (e) {
    toast(e, "error");
  }
}

async function stopFarm() {
  try {
    await invoke("farm_stop");
    toast("Farm stopped", "success");
    updateFarmStatus();
  } catch (e) { toast(e, "error"); }
}

function updateFarmStatus() {
  const start = $("#farm-start");
  const stop = $("#farm-stop");
  const status = $("#farm-status");
  const queue = $("#farm-queue");
  if (!start) return;
  if (farm && farm.active) {
    start.classList.add("hidden");
    stop.classList.remove("hidden");
    if (queue) queue.innerHTML = "";
    status.textContent = `Farming game ${farm.index + 1}/${farm.total} — ${farm.current || ""} (${farm.minutes_per_game} min)`;
  } else {
    start.classList.remove("hidden");
    stop.classList.add("hidden");
    status.textContent = farmQueue.length ? `${farmQueue.length} game${farmQueue.length === 1 ? "" : "s"} queued` : "";
  }
}

/* ── library view ────────────────────────────────────── */
function renderLibrary(query) {
  const wrap = $("#view-library");
  const q = (query || "").trim().toLowerCase();
  wrap.innerHTML = `
    <div class="lib-toolbar">
      <input id="lib-search" class="lib-input" placeholder="Search ${games.length.toLocaleString()} games…" value="${esc(query || "")}" />
    </div>
    <div id="lib-list" class="lib-list"></div>`;

  const list = $("#lib-list");
  if (!games.length) {
    list.innerHTML = `<div class="loading"><div class="spinner"></div> Loading…</div>`;
    return;
  }
  const matches = q
    ? games.filter((g) => g.name.toLowerCase().includes(q))
    : games.slice(0, 200);
  if (!matches.length) {
    list.innerHTML = `<div class="empty" style="height:auto;padding:40px 0"><div class="empty-icon">🔍</div><div class="empty-title">No games found</div></div>`;
    return;
  }
  list.innerHTML = matches.map((g) => `
    <button class="lib-row" data-id="${esc(g.id)}">
      <div class="lib-icon">🎮</div>
      <div style="min-width:0">
        <div class="lib-name">${esc(g.name)}</div>
        <div class="lib-exes">${g.executables.length} executable${g.executables.length === 1 ? "" : "s"}${g.hook ? " · hook" : ""}</div>
      </div>
      <span class="btn brand sm lib-add">＋</span>
    </button>`).join("");

  $$(".lib-row").forEach((row) => {
    row.addEventListener("click", () => {
      const game = games.find((g) => g.id === row.dataset.id);
      if (game) openModal(game);
    });
  });
  const libSearch = $("#lib-search");
  libSearch.addEventListener("input", debounce((e) => renderLibrary(e.target.value), 250));
}

/* ── settings view ───────────────────────────────────── */
function renderSettings() {
  const wrap = $("#view-settings");
  wrap.innerHTML = `
    <div class="settings-card">
      <h2>Settings</h2>
      <div class="set-row">
        <div class="set-label">Default duration<span class="desc">Used when adding a new quest</span></div>
        <div class="dur-row">
          <input id="set-minutes" class="input dur" type="number" min="1" max="1440" value="${settings.default_minutes || 15}" />
          <span class="hint">min</span>
        </div>
      </div>
      <div class="set-row">
        <div class="set-label">Game list<span class="desc">${games.length.toLocaleString()} games loaded from Discord API</span></div>
        <button class="btn ghost sm" id="set-refresh">↻ Refresh</button>
      </div>
      <div class="set-row">
        <div class="set-label">Stop everything<span class="desc">Kill all running quests</span></div>
        <button class="btn danger sm" id="set-stopall">Stop All</button>
      </div>
      <div class="set-row">
        <div class="set-label">About<span class="desc">Discord Quest Completer · Tauri edition</span></div>
        <span class="hint">v1.0.0</span>
      </div>
    </div>`;

  $("#set-refresh").addEventListener("click", async () => {
    toast("Refreshing game list…", "warn");
    try {
      games = await invoke("fetch_games", { force: true });
      $("#game-count").textContent = games.length.toLocaleString();
      toast(`Loaded ${games.length.toLocaleString()} games`, "success");
    } catch (e) { toast(e, "error"); }
  });
  $("#set-stopall").addEventListener("click", async () => {
    const ids = quests.map((q) => q.id);
    for (const id of ids) {
      try { await invoke("stop_quest", { id }); } catch (e) {}
    }
    toast("All quests stopped");
  });
  const minutes = $("#set-minutes");
  minutes.addEventListener("change", async () => {
    try {
      const m = parseInt(minutes.value, 10) || 15;
      await invoke("set_default_minutes", { minutes: m });
      settings.default_minutes = m;
      $("#aq-minutes").value = m;
      toast("Default duration saved", "success");
    } catch (e) { toast(e, "error"); }
  });
}

/* ── add quest modal ─────────────────────────────────── */
function bindTopbar() {
  $("#btn-add").addEventListener("click", openModal);
}

function openModal(game) {
  selectedGame = game || null;
  $("#modal").classList.remove("hidden");
  const search = $("#aq-search");
  search.value = "";
  $("#aq-results").innerHTML = "";
  $("#aq-config").classList.add("hidden");
  $("#aq-launch").disabled = true;
  if (game) {
    selectGame(game);
  } else {
    setTimeout(() => search.focus(), 50);
    searchResults("");
  }
}

function bindModal() {
  $("#modal-close").addEventListener("click", closeModal);
  $("#modal").addEventListener("click", (e) => {
    if (e.target === $("#modal")) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#modal").classList.contains("hidden")) closeModal();
  });
  $("#aq-search").addEventListener("input", debounce((e) => searchResults(e.target.value), 200));
  $("#aq-exe-manual").addEventListener("input", (e) => {
    if (e.target.value.trim()) enableLaunch();
  });
  $("#aq-launch").addEventListener("click", launchQuest);
}

function closeModal() {
  $("#modal").classList.add("hidden");
}

function searchResults(q) {
  const wrap = $("#aq-results");
  const query = (q || "").trim().toLowerCase();
  if (!query) {
    wrap.innerHTML = "";
    return;
  }
  const matches = games.filter((g) => g.name.toLowerCase().includes(query)).slice(0, 25);
  if (!matches.length) {
    wrap.innerHTML = `<div class="warn">No games found. Try a different name.</div>`;
    return;
  }
  wrap.innerHTML = matches.map((g) => `
    <button class="aq-result" data-id="${esc(g.id)}">
      <span>🎮</span>
      <span>${esc(g.name)}</span>
      <span class="exe-badge">${g.executables.length} exe</span>
    </button>`).join("");
  $$(".aq-result").forEach((row) => {
    row.addEventListener("click", () => {
      const game = games.find((g) => g.id === row.dataset.id);
      if (game) selectGame(game);
    });
  });
}

function selectGame(game) {
  selectedGame = game;
  $("#aq-results").innerHTML = "";
  $("#aq-config").classList.remove("hidden");
  $("#aq-game-name").textContent = game.name;

  const meta = [];
  if (game.executables.length) meta.push(`${game.executables.length} executable(s)`);
  if (game.hook) meta.push("Discord hook");
  $("#aq-game-meta").textContent = meta.join(" · ");

  const exesWrap = $("#aq-exes");
  const manual = $("#aq-exe-manual");
  const warn = $("#aq-warn");

  if (game.executables.length) {
    manual.classList.add("hidden");
    warn.classList.add("hidden");
    exesWrap.innerHTML = game.executables.map((exe, i) =>
      `<button class="aq-exe ${i === 0 ? "selected" : ""}" data-exe="${esc(exe)}">${esc(exe)}</button>`
    ).join("");
    $$(".aq-exe").forEach((btn) => {
      btn.addEventListener("click", () => {
        $$(".aq-exe").forEach((b) => b.classList.remove("selected"));
        btn.classList.add("selected");
        enableLaunch();
      });
    });
  } else {
    exesWrap.innerHTML = "";
    warn.classList.remove("hidden");
    warn.textContent = "This game has no executables in Discord's database. Discord may not detect it — enter the process name manually.";
    manual.classList.remove("hidden");
    manual.value = game.name.replace(/\s+/g, "") + ".exe";
    manual.focus();
  }
  enableLaunch();
}

function enableLaunch() {
  const hasExe = selectedGame && (
    selectedGame.executables.length > 0 || $("#aq-exe-manual").value.trim()
  );
  $("#aq-launch").disabled = !hasExe;
}

async function launchQuest() {
  if (!selectedGame) return;
  let exeName;
  const selectedExe = $(".aq-exe.selected");
  if (selectedExe) {
    exeName = selectedExe.dataset.exe;
  } else {
    exeName = $("#aq-exe-manual").value.trim();
  }
  if (!exeName) {
    toast("Enter an executable name", "error");
    return;
  }
  const minutes = parseInt($("#aq-minutes").value, 10) || 15;
  $("#aq-launch").disabled = true;
  try {
    const info = await invoke("start_quest", { gameName: selectedGame.name, exeName, minutes });
    closeModal();
    renderView("quests");
    toast(`Quest started: ${info.name}`, "success");
  } catch (e) {
    toast(e, "error");
    $("#aq-launch").disabled = false;
  }
}

/* ── go ──────────────────────────────────────────────── */
boot();

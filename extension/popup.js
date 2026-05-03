// Droply popup — reads auth + counters from chrome.storage.local.
const CONFIG = {
  API_URL: "http://localhost:8000",
  APP_URL: "http://localhost:3000",
};

const $ = (id) => document.getElementById(id);

function show(elId) {
  $(elId).classList.remove("hidden");
}
function hide(elId) {
  $(elId).classList.add("hidden");
}

function render(state) {
  if (state.token) {
    show("logged-in");
    hide("logged-out");
    $("ebay-username").textContent = state.ebayUsername || "Not connected";
    $("today-count").textContent = state.todayCount || 0;
    $("today-date").textContent = state.todayDate || "";
    $("dashboard-link").href = `${CONFIG.APP_URL}/dashboard`;
  } else {
    show("logged-out");
    hide("logged-in");
    $("login-link").href = `${CONFIG.APP_URL}/login`;
  }
}

async function load() {
  chrome.storage.local.get(
    ["droply_token", "droply_ebay_username", "droply_today"],
    async (res) => {
      const today = new Date().toISOString().slice(0, 10);
      const counter = res.droply_today && res.droply_today.date === today ? res.droply_today : { date: today, count: 0 };

      let ebayUsername = res.droply_ebay_username || "";
      // Best-effort refresh of ebay username from backend.
      if (res.droply_token) {
        try {
          const r = await fetch(`${CONFIG.API_URL}/api/me`, {
            headers: { Authorization: `Bearer ${res.droply_token}` },
          });
          if (r.ok) {
            const j = await r.json();
            ebayUsername = j.ebay_username || ebayUsername;
            chrome.storage.local.set({ droply_ebay_username: ebayUsername });
          }
        } catch {}
      }

      render({
        token: res.droply_token,
        ebayUsername,
        todayCount: counter.count,
        todayDate: counter.date,
      });
    },
  );
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("logout-btn")?.addEventListener("click", () => {
    chrome.storage.local.remove(["droply_token", "droply_ebay_username"], () => load());
  });
});

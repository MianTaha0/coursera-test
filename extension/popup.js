// Droply popup — inline login + status. Reads/writes chrome.storage.local.
const CONFIG = {
  API_URL: "http://localhost:8000",
  APP_URL: "http://localhost:3000",
};

const $ = (id) => document.getElementById(id);
const show = (id) => $(id).classList.remove("hidden");
const hide = (id) => $(id).classList.add("hidden");

function render(state) {
  if (state.token) {
    show("logged-in"); hide("logged-out");
    $("ebay-username").textContent = state.ebayUsername || "Not connected";
    $("today-count").textContent = state.todayCount || 0;
    $("today-date").textContent = state.todayDate || "";
    $("dashboard-link").href = `${CONFIG.APP_URL}/dashboard`;
  } else {
    show("logged-out"); hide("logged-in");
    $("signup-link").href = `${CONFIG.APP_URL}/signup`;
  }
}

function showError(msg) {
  const el = $("err");
  el.textContent = msg;
  el.classList.remove("hidden");
}

async function refreshMe(token) {
  try {
    const r = await fetch(`${CONFIG.API_URL}/api/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) return null;
    const j = await r.json();
    return j.ebay_username || null;
  } catch {
    return null;
  }
}

async function load() {
  chrome.storage.local.get(
    ["droply_token", "droply_ebay_username", "droply_today"],
    async (res) => {
      const today = new Date().toISOString().slice(0, 10);
      const counter = res.droply_today && res.droply_today.date === today
        ? res.droply_today
        : { date: today, count: 0 };

      let ebayUsername = res.droply_ebay_username || "";
      if (res.droply_token) {
        const fresh = await refreshMe(res.droply_token);
        if (fresh) {
          ebayUsername = fresh;
          chrome.storage.local.set({ droply_ebay_username: ebayUsername });
        }
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

async function login(email, password) {
  const btn = $("login-btn");
  btn.disabled = true;
  btn.textContent = "Signing in…";
  $("err").classList.add("hidden");
  try {
    const r = await fetch(`${CONFIG.API_URL}/api/auth/extension`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      showError(j.detail || `Sign in failed (${r.status})`);
      return;
    }
    chrome.storage.local.set(
      { droply_token: j.access_token },
      () => load(),
    );
  } catch (e) {
    showError(`Cannot reach Droply API at ${CONFIG.API_URL}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign in";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("login-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    login($("email").value.trim(), $("password").value);
  });
  $("logout-btn")?.addEventListener("click", () => {
    chrome.storage.local.remove(
      ["droply_token", "droply_ebay_username"],
      () => load(),
    );
  });
});

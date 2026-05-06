// Droply popup — local storage + optional backend.

const DEFAULT_BACKEND = "http://localhost:8000";
const $ = (id) => document.getElementById(id);

function fmtPrice(p, c) {
  if (p == null) return "—";
  try { return new Intl.NumberFormat("en-US", { style: "currency", currency: c || "USD" }).format(p); }
  catch { return `${p}`; }
}

function render(state) {
  $("today-count").textContent = state.today;
  $("total-count").textContent = state.imports.length;

  const list = $("list");
  list.innerHTML = "";
  if (!state.imports.length) {
    $("empty").style.display = "block";
    return;
  }
  $("empty").style.display = "none";

  for (const item of state.imports.slice(0, 30)) {
    const row = document.createElement("div");
    row.className = "item";

    const img = document.createElement("img");
    img.src = (item.images && item.images[0]) || "";
    img.alt = "";
    row.appendChild(img);

    const body = document.createElement("div");
    body.className = "body";

    const title = document.createElement("div");
    title.className = "title";
    title.title = item.title || item.asin;
    title.textContent = item.title || item.asin;
    body.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${fmtPrice(item.price, item.currency)} · ${item.asin}`;
    body.appendChild(meta);

    if (item.amazon_url) {
      const link = document.createElement("a");
      link.href = item.amazon_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Open on Amazon";
      body.appendChild(link);
    }

    row.appendChild(body);

    const remove = document.createElement("button");
    remove.className = "remove";
    remove.title = "Remove";
    remove.textContent = "×";
    remove.addEventListener("click", () => removeItem(item.asin));
    row.appendChild(remove);

    list.appendChild(row);
  }
}

function load() {
  chrome.storage.local.get(
    ["droply_imports", "droply_today", "droply_backend_url"],
    (res) => {
      const today = new Date().toISOString().slice(0, 10);
      const counter = res.droply_today && res.droply_today.date === today
        ? res.droply_today
        : { date: today, count: 0 };
      render({
        imports: Array.isArray(res.droply_imports) ? res.droply_imports : [],
        today: counter.count,
      });
      $("backend-url").value = res.droply_backend_url || "";
      $("backend-url").placeholder = DEFAULT_BACKEND;
    },
  );
}

function removeItem(asin) {
  chrome.storage.local.get(["droply_imports"], (res) => {
    const next = (res.droply_imports || []).filter((x) => x.asin !== asin);
    chrome.storage.local.set({ droply_imports: next }, load);
  });
}

function clearAll() {
  if (!confirm("Clear all saved products?")) return;
  chrome.storage.local.remove(["droply_imports"], load);
}

function copyJson() {
  chrome.storage.local.get(["droply_imports"], (res) => {
    const json = JSON.stringify(res.droply_imports || [], null, 2);
    navigator.clipboard.writeText(json).then(
      () => {
        const btn = $("export-btn");
        const old = btn.textContent;
        btn.textContent = "Copied ✓";
        setTimeout(() => (btn.textContent = old), 1500);
      },
      () => alert("Could not copy to clipboard"),
    );
  });
}

function fmtRelative(iso) {
  if (!iso) return "Never run";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "Just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function refreshRecheckStatus() {
  chrome.runtime.sendMessage({ type: "DROPLY_RECHECK_STATUS" }, (res) => {
    const el = $("recheck-status");
    if (!el) return;
    if (chrome.runtime.lastError || !res) {
      el.textContent = "Background worker not ready";
      return;
    }
    if (res.running) {
      el.textContent = "Recheck in progress…";
      el.style.color = "#22c55e";
    } else {
      el.textContent = `Last run: ${fmtRelative(res.last_at)}`;
      el.style.color = "";
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("clear-btn").addEventListener("click", clearAll);
  $("export-btn").addEventListener("click", copyJson);

  // Recheck-all button
  $("recheck-now-btn").addEventListener("click", () => {
    const btn = $("recheck-now-btn");
    btn.disabled = true;
    btn.textContent = "Running…";
    chrome.runtime.sendMessage({ type: "DROPLY_RECHECK_NOW" }, (res) => {
      btn.disabled = false;
      btn.textContent = "Recheck all";
      if (chrome.runtime.lastError || !res?.ok) {
        $("recheck-status").textContent = "Failed — see console";
      } else {
        $("recheck-status").textContent = `Re-checked ${res.count} product${res.count === 1 ? "" : "s"}`;
      }
      refreshRecheckStatus();
    });
  });

  // Interval selector
  chrome.storage.local.get(["droply_recheck_interval_min"], (res) => {
    const sel = $("recheck-interval");
    if (res.droply_recheck_interval_min) sel.value = String(res.droply_recheck_interval_min);
  });
  $("recheck-interval").addEventListener("change", (e) => {
    const minutes = Number(e.target.value);
    chrome.storage.local.set({ droply_recheck_interval_min: minutes }, () => {
      // Re-arm the alarm with the new interval
      chrome.alarms.create("droply-recheck-all", {
        delayInMinutes: minutes,
        periodInMinutes: minutes,
      });
    });
  });

  refreshRecheckStatus();
  setInterval(refreshRecheckStatus, 3000);
  $("amazon-btn").addEventListener("click", () => {
    chrome.tabs.create({ url: "https://www.amazon.com/" });
  });
  $("library-btn").addEventListener("click", () => {
    chrome.tabs.create({ url: chrome.runtime.getURL("library.html") });
  });
  $("dashboard-btn").addEventListener("click", () => {
    chrome.storage.local.get(["droply_backend_url"], (res) => {
      const base = (res.droply_backend_url || DEFAULT_BACKEND).replace(/:\d+$/, ":3000").replace(/^https?:\/\/([^:/]+).*/, "http://$1:3000");
      chrome.tabs.create({ url: base });
    });
  });
  $("save-backend-btn").addEventListener("click", () => {
    const v = $("backend-url").value.trim().replace(/\/+$/, "");
    chrome.storage.local.set({ droply_backend_url: v }, () => {
      const btn = $("save-backend-btn");
      const old = btn.textContent;
      btn.textContent = "Saved ✓";
      setTimeout(() => (btn.textContent = old), 1200);
    });
  });

  // Live update if storage changes while popup is open.
  chrome.storage.onChanged.addListener((_changes, area) => {
    if (area === "local") load();
  });
});

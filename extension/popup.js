// Droply popup — pure local storage. No backend, no login.

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
  chrome.storage.local.get(["droply_imports", "droply_today"], (res) => {
    const today = new Date().toISOString().slice(0, 10);
    const counter = res.droply_today && res.droply_today.date === today
      ? res.droply_today
      : { date: today, count: 0 };
    render({
      imports: Array.isArray(res.droply_imports) ? res.droply_imports : [],
      today: counter.count,
    });
  });
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

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("clear-btn").addEventListener("click", clearAll);
  $("export-btn").addEventListener("click", copyJson);
  $("amazon-btn").addEventListener("click", () => {
    chrome.tabs.create({ url: "https://www.amazon.com/" });
  });
  $("library-btn").addEventListener("click", () => {
    chrome.tabs.create({ url: chrome.runtime.getURL("library.html") });
  });

  // Live update if storage changes while popup is open.
  chrome.storage.onChanged.addListener((_changes, area) => {
    if (area === "local") load();
  });
});

// Droply Library — full-page view of everything saved to chrome.storage.local.

const $ = (id) => document.getElementById(id);

let ALL = [];        // raw imports
let FILTERED = [];   // post-search/sort

function fmtPrice(p, c) {
  if (p == null || isNaN(Number(p))) return "—";
  try { return new Intl.NumberFormat("en-US", { style: "currency", currency: c || "USD" }).format(Number(p)); }
  catch { return `${p}`; }
}
function fmtDate(s) {
  if (!s) return "";
  const d = new Date(s);
  return isNaN(d.getTime()) ? "" : d.toLocaleString();
}

function load() {
  chrome.storage.local.get(["droply_imports", "droply_today"], (res) => {
    ALL = Array.isArray(res.droply_imports) ? res.droply_imports : [];
    const today = new Date().toISOString().slice(0, 10);
    const counter = res.droply_today && res.droply_today.date === today ? res.droply_today : { date: today, count: 0 };

    $("s-total").textContent = ALL.length;
    $("s-today").textContent = counter.count;
    const prices = ALL.map((x) => Number(x.price)).filter((n) => isFinite(n) && n > 0);
    $("s-avg").textContent = prices.length
      ? fmtPrice(prices.reduce((a, b) => a + b, 0) / prices.length, ALL[0]?.currency || "USD")
      : "—";
    $("s-stock").textContent = ALL.filter((x) => x.stock_status !== "out_of_stock").length;

    apply();
  });
}

function apply() {
  const q = $("q").value.trim().toLowerCase();
  let arr = !q ? ALL.slice() : ALL.filter((x) =>
    [x.title, x.brand, x.asin].some((f) => (f || "").toLowerCase().includes(q)),
  );
  switch ($("sort").value) {
    case "price-asc":  arr.sort((a, b) => (a.price || 0) - (b.price || 0)); break;
    case "price-desc": arr.sort((a, b) => (b.price || 0) - (a.price || 0)); break;
    case "title":      arr.sort((a, b) => (a.title || "").localeCompare(b.title || "")); break;
    default:           arr.sort((a, b) => new Date(b.saved_at || 0) - new Date(a.saved_at || 0));
  }
  FILTERED = arr;
  draw();
}

function draw() {
  const grid = $("grid");
  grid.innerHTML = "";
  if (!FILTERED.length) {
    $("empty").style.display = "block";
    return;
  }
  $("empty").style.display = "none";

  const frag = document.createDocumentFragment();
  for (const p of FILTERED) {
    const card = document.createElement("article");
    card.className = "card";

    const thumb = document.createElement("div");
    thumb.className = "thumb";
    if (p.images && p.images[0]) {
      const img = document.createElement("img");
      img.src = p.images[0]; img.alt = "";
      img.referrerPolicy = "no-referrer";
      thumb.appendChild(img);
    }
    card.appendChild(thumb);

    const body = document.createElement("div");
    body.className = "body";

    const meta = document.createElement("div");
    meta.className = "meta";
    const stock = document.createElement("span");
    stock.className = "badge" + (p.stock_status === "out_of_stock" ? " out" : "");
    stock.textContent = p.stock_status === "out_of_stock" ? "Out of stock" : "In stock";
    meta.appendChild(stock);
    const date = document.createElement("span");
    date.textContent = fmtDate(p.saved_at);
    meta.appendChild(date);
    body.appendChild(meta);

    const title = document.createElement("div");
    title.className = "title";
    title.title = p.title || p.asin || "";
    title.textContent = p.title || p.asin || "(untitled)";
    body.appendChild(title);

    const price = document.createElement("div");
    price.className = "price";
    price.textContent = fmtPrice(p.price, p.currency);
    body.appendChild(price);

    const sub = document.createElement("div");
    sub.className = "meta";
    sub.innerHTML = `<span>${p.brand || ""}</span><span>${p.asin || ""}</span>`;
    body.appendChild(sub);

    const footer = document.createElement("div");
    footer.className = "footer";
    if (p.amazon_url) {
      const a = document.createElement("a");
      a.href = p.amazon_url; a.target = "_blank"; a.rel = "noopener";
      a.textContent = "Amazon";
      footer.appendChild(a);
    }
    const copy = document.createElement("button");
    copy.textContent = "Copy JSON";
    copy.addEventListener("click", () => {
      navigator.clipboard.writeText(JSON.stringify(p, null, 2));
      copy.textContent = "Copied ✓";
      setTimeout(() => (copy.textContent = "Copy JSON"), 1200);
    });
    footer.appendChild(copy);
    const rm = document.createElement("button");
    rm.className = "remove";
    rm.textContent = "Remove";
    rm.addEventListener("click", () => removeOne(p.asin));
    footer.appendChild(rm);
    body.appendChild(footer);

    card.appendChild(body);
    frag.appendChild(card);
  }
  grid.appendChild(frag);
}

function removeOne(asin) {
  chrome.storage.local.get(["droply_imports"], (res) => {
    const next = (res.droply_imports || []).filter((x) => x.asin !== asin);
    chrome.storage.local.set({ droply_imports: next }, load);
  });
}

function clearAll() {
  if (!confirm(`Clear all ${ALL.length} saved products?`)) return;
  chrome.storage.local.remove(["droply_imports"], load);
}

function downloadBlob(filename, mime, data) {
  const blob = new Blob([data], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportJson() {
  downloadBlob("droply-library.json", "application/json", JSON.stringify(ALL, null, 2));
}

function csvCell(v) {
  if (v == null) return "";
  const s = String(v).replace(/"/g, '""');
  return /[",\n]/.test(s) ? `"${s}"` : s;
}
function exportCsv() {
  const headers = ["asin","title","brand","price","currency","stock_status","amazon_url","saved_at","images"];
  const rows = [headers.join(",")];
  for (const p of ALL) {
    rows.push([
      csvCell(p.asin), csvCell(p.title), csvCell(p.brand),
      csvCell(p.price), csvCell(p.currency), csvCell(p.stock_status),
      csvCell(p.amazon_url), csvCell(p.saved_at),
      csvCell((p.images || []).join(" | ")),
    ].join(","));
  }
  downloadBlob("droply-library.csv", "text/csv", rows.join("\n"));
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("q").addEventListener("input", apply);
  $("sort").addEventListener("change", apply);
  $("clear").addEventListener("click", clearAll);
  $("export-json").addEventListener("click", exportJson);
  $("export-csv").addEventListener("click", exportCsv);

  chrome.storage.onChanged.addListener((_changes, area) => {
    if (area === "local") load();
  });
});

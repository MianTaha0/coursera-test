// Droply — AliExpress product scraper + "Save product" injector.
// Same storage / retry / notify surface as the Amazon scraper; only the
// extraction logic differs. The payload's `asin` slot is set to
// "ALI-{item_id}" so AliExpress products coexist with Amazon ones in the
// shared backend table.
(() => {
  const MAX_STORED = 200;
  const BACKEND_URL_KEY = "droply_backend_url";
  const DEFAULT_BACKEND = "http://localhost:8000";
  const RETRY_QUEUE_KEY = "droply_retry_queue";
  const MAX_RETRY_QUEUE = 100;

  // ---------- DOM helpers ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const meta = (name) => {
    const el = document.querySelector(
      `meta[property="${name}"], meta[name="${name}"]`,
    );
    return el ? (el.getAttribute("content") || "").trim() : "";
  };

  // ---------- Scraper ----------
  function extractItemId() {
    // AliExpress URLs are of the shape /item/{numeric_id}.html
    const m = location.pathname.match(/\/item\/(\d{6,})\.html/);
    if (m) return m[1];
    const m2 = location.pathname.match(/\/item\/(\d{6,})\b/);
    if (m2) return m2[1];
    // Some sponsored / promo pages put the id in a query param
    const qs = new URLSearchParams(location.search).get("productId");
    if (qs && /^\d{6,}$/.test(qs)) return qs;
    return null;
  }

  function extractTitle() {
    // og:title is the most reliable signal across AliExpress's React refreshes
    const og = meta("og:title");
    if (og) return og;
    return text($("h1")) || text($("[data-pl='product-title']"));
  }

  // AliExpress shows prices in many regional formats. Reuse the EU/US
  // separator-detection logic from the Amazon scraper.
  function parsePrice(str) {
    if (!str) return null;
    let s = String(str).replace(/[^\d.,]/g, "");
    if (!s) return null;
    const lastComma = s.lastIndexOf(",");
    const lastDot = s.lastIndexOf(".");
    if (lastComma > -1 && lastDot > -1) {
      if (lastComma > lastDot) s = s.replace(/\./g, "").replace(",", ".");
      else s = s.replace(/,/g, "");
    } else if (lastComma > -1) {
      const after = s.length - lastComma - 1;
      s = after === 2 ? s.replace(",", ".") : s.replace(/,/g, "");
    }
    const n = parseFloat(s);
    return isFinite(n) && n > 0 ? n : null;
  }

  function extractPrice() {
    // Strongest signal: og:price:amount meta tag.
    const og = meta("og:price:amount") || meta("product:price:amount");
    if (og) {
      const n = parsePrice(og);
      if (n) return n;
    }
    // Fall back to DOM selectors. AliExpress changes class names every few
    // months; try several known patterns + a generic class-prefix sweep.
    const sels = [
      ".product-price-value",
      "[class*='Product_Price_'] [class*='promotionPrice']",
      "[class*='ProductPrice'] [class*='Price']",
      "[class*='product-price-current']",
      "[class*='priceArea'] [class*='Price']",
      "[data-pl='product-price']",
    ];
    for (const sel of sels) {
      const el = $(sel);
      if (!el) continue;
      const n = parsePrice(text(el));
      if (n) return n;
    }
    // Last-ditch: the first "$N.NN"-like token on the page.
    const body = text(document.body).slice(0, 4000);
    const m = body.match(/(?:US\s*\$|\$|€|£|¥|₽)\s*(\d{1,5}(?:[.,]\d{1,2})?)/);
    if (m) {
      const n = parsePrice(m[1]);
      if (n) return n;
    }
    return null;
  }

  function extractCurrency() {
    const og = meta("og:price:currency") || meta("product:price:currency");
    if (og) return og.toUpperCase();
    // Symbol probe on the displayed price.
    const t =
      text($(".product-price-value")) ||
      text($("[class*='ProductPrice'] [class*='Price']")) ||
      text($("[class*='product-price-current']")) ||
      "";
    if (t.includes("US$") || t.includes("$")) return "USD";
    if (t.includes("£")) return "GBP";
    if (t.includes("€")) return "EUR";
    if (t.includes("¥")) return "JPY";
    if (t.includes("₽")) return "RUB";
    // Hostname fallback — AliExpress regionalises by subdomain
    if (location.hostname.startsWith("ru.")) return "RUB";
    if (location.hostname.startsWith("de.") || location.hostname.startsWith("fr.") ||
        location.hostname.startsWith("it.") || location.hostname.startsWith("es.") ||
        location.hostname.startsWith("nl.") || location.hostname.startsWith("pt.")) return "EUR";
    return "USD";
  }

  // Strip AliExpress CDN size suffixes (e.g. ".jpg_220x220.webp" → ".jpg").
  function normaliseImage(src) {
    if (!src) return "";
    let s = src;
    if (s.startsWith("//")) s = "https:" + s;
    if (!/^https?:/.test(s)) return "";
    // ".jpg_220x220.webp", ".jpg_50x50q75.jpg_.webp", "_640x640.jpg" — strip
    // anything after the first plausible filename extension.
    return s.replace(/(\.(?:jpg|jpeg|png|webp))(?:_.*)?$/i, "$1");
  }

  function extractImages() {
    const urls = new Set();
    const og = meta("og:image");
    if (og) urls.add(normaliseImage(og));
    const candidates = [
      "[class*='Image_imageGallery'] img",
      "[class*='magnifier'] img",
      "[class*='image-thumb'] img",
      ".image-view img",
      ".product-main-image img",
      "[data-pl='product-image'] img",
    ];
    for (const sel of candidates) {
      $$(sel).forEach((img) => {
        const src =
          img.getAttribute("src") ||
          img.getAttribute("data-src") ||
          img.getAttribute("data-srcset")?.split(/\s+/)[0] ||
          "";
        const norm = normaliseImage(src);
        if (norm) urls.add(norm);
      });
    }
    return Array.from(urls).filter((u) => /^https?:/.test(u)).slice(0, 12);
  }

  function extractStock() {
    const body = text(document.body);
    // AliExpress has many phrasings; check the strong negatives first
    if (/(out of stock|sold out|no longer available|item is unavailable)/i.test(body)) {
      return "out_of_stock";
    }
    // "0 pieces available" / "Last 1 piece left" — both are still in_stock to
    // eBay's eyes; only flag OOS when the source page explicitly says so.
    return "in_stock";
  }

  // AliExpress products rarely have a meaningful Brand value. Look in the
  // properties table first, then fall back to the og:brand meta tag if present.
  function extractBrand() {
    const ogBrand = meta("og:brand") || meta("product:brand");
    if (ogBrand) return ogBrand;
    const rows = $$(
      ".product-prop, [class*='product-specs'] li, [class*='product-property'] li, .specification--list--item",
    );
    for (const row of rows) {
      const t = text(row);
      if (/^brand\s*name?\s*[:：]/i.test(t)) {
        return t.replace(/^brand\s*name?\s*[:：]\s*/i, "").slice(0, 60);
      }
    }
    return "";
  }

  // Spec table — same key/value shape the backend uses to auto-fill eBay
  // item-specifics (Phase 2.2).
  function extractSpecTable() {
    const out = {};
    const rows = $$(
      ".product-prop, [class*='product-specs'] li, [class*='product-property-list'] li, .specification--list--item, .specifications-list li",
    );
    for (const row of rows) {
      // Two common DOM shapes:
      //   <li><span>Brand Name</span><span>Acme</span></li>
      //   "Brand Name: Acme"
      const spans = row.querySelectorAll("span, div");
      if (spans.length >= 2) {
        const k = text(spans[0]).replace(/[:：\s]+$/, "").trim();
        const v = text(spans[1]).trim();
        if (k && v && k.length <= 60 && !out[k]) {
          out[k] = v.slice(0, 200);
          continue;
        }
      }
      const t = text(row);
      const m = t.match(/^([^:：]{1,60})[:：]\s*(.+)$/);
      if (m && !out[m[1]]) {
        out[m[1].trim()] = m[2].trim().slice(0, 200);
      }
    }
    // Drop noisy / non-product keys that some templates leak in
    for (const k of Object.keys(out)) {
      if (/^(reviews?|rating|orders|free shipping|delivery)$/i.test(k)) {
        delete out[k];
      }
    }
    return out;
  }

  function scrape() {
    const itemId = extractItemId();
    if (!itemId) return null;
    return {
      // Universal product key in the backend. Prefix with ALI- so AliExpress
      // and Amazon products coexist in the same `products` table.
      asin: `ALI-${itemId}`,
      title: extractTitle(),
      price: extractPrice(),
      currency: extractCurrency(),
      images: extractImages(),
      description: "",  // AliExpress descriptions are iframe'd image carousels — skip for now
      stock_status: extractStock(),
      brand: extractBrand(),
      spec_table: extractSpecTable(),
      // The backend keeps an `amazon_url` column as a generic "source URL".
      // For AliExpress products we write the AliExpress URL here.
      amazon_url: `https://${location.hostname}/item/${itemId}.html`,
      source_marketplace: location.hostname,
      saved_at: new Date().toISOString(),
    };
  }

  // ---------- Save to chrome.storage.local ----------
  function saveLocal(item) {
    return new Promise((resolve, reject) => {
      chrome.storage.local.get(["droply_imports", "droply_today"], (res) => {
        const imports = Array.isArray(res.droply_imports) ? res.droply_imports : [];
        const filtered = imports.filter((x) => x.asin !== item.asin);
        const next = [item, ...filtered].slice(0, MAX_STORED);
        const today = new Date().toISOString().slice(0, 10);
        const counter = res.droply_today && res.droply_today.date === today
          ? res.droply_today
          : { date: today, count: 0 };
        counter.count += 1;
        chrome.storage.local.set({ droply_imports: next, droply_today: counter }, () => {
          if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
          else resolve(next.length);
        });
      });
    });
  }

  // ---------- Best-effort push to backend ----------
  function getBackendUrl() {
    return new Promise((resolve) => {
      chrome.storage.local.get([BACKEND_URL_KEY], (res) => {
        resolve(res[BACKEND_URL_KEY] || DEFAULT_BACKEND);
      });
    });
  }

  async function pushToBackend(item) {
    const url = await getBackendUrl();
    if (!url) return { ok: false, skipped: true };
    try {
      const r = await fetch(`${url}/api/products`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item),
      });
      return { ok: r.ok, status: r.status };
    } catch (e) {
      return { ok: false, error: String(e.message || e) };
    }
  }

  async function enqueueRetry(item) {
    return new Promise((resolve) => {
      chrome.storage.local.get([RETRY_QUEUE_KEY], (res) => {
        const queue = Array.isArray(res[RETRY_QUEUE_KEY]) ? res[RETRY_QUEUE_KEY] : [];
        const filtered = queue.filter((q) => q.asin !== item.asin);
        filtered.push(item);
        const trimmed = filtered.slice(-MAX_RETRY_QUEUE);
        chrome.storage.local.set({ [RETRY_QUEUE_KEY]: trimmed }, () => resolve(trimmed.length));
      });
    });
  }

  async function saveImport(item) {
    const total = await saveLocal(item);
    const push = await pushToBackend(item);
    if (!push.ok) {
      try { await enqueueRetry(item); } catch (_) { /* swallow */ }
      try { chrome.runtime.sendMessage({ type: "DROPLY_RETRY_NUDGE" }); } catch (_) { /* swallow */ }
    }
    return { total, push };
  }

  // ---------- Button injector ----------
  function makeButton() {
    const btn = document.createElement("button");
    btn.id = "droply-import-btn";
    btn.type = "button";
    btn.textContent = "Save product (Droply)";
    Object.assign(btn.style, {
      display: "block",
      width: "100%",
      margin: "10px 0",
      padding: "12px 16px",
      background: "#22c55e",
      color: "#0b0d12",
      border: "none",
      borderRadius: "10px",
      fontSize: "15px",
      fontWeight: "700",
      cursor: "pointer",
      boxShadow: "0 2px 8px rgba(34,197,94,.35)",
      transition: "background .15s ease",
    });
    btn.addEventListener("mouseenter", () => {
      if (!btn.dataset.locked) btn.style.background = "#16a34a";
    });
    btn.addEventListener("mouseleave", () => {
      if (!btn.dataset.locked) btn.style.background = "#22c55e";
    });
    return btn;
  }

  function setBtnState(btn, state, label) {
    btn.dataset.locked = state === "loading" || state === "success" || state === "error" ? "1" : "";
    btn.disabled = state === "loading";
    btn.textContent = label;
    if (state === "loading") btn.style.background = "#6b7280";
    else if (state === "success") btn.style.background = "#16a34a";
    else if (state === "error") { btn.style.background = "#dc2626"; btn.style.color = "#fff"; }
    else btn.style.background = "#22c55e";
  }

  async function onClick(btn) {
    setBtnState(btn, "loading", "Saving…");
    const data = scrape();
    if (!data || !data.asin) {
      setBtnState(btn, "error", "Could not read product data");
      return;
    }
    try {
      const { total, push } = await saveImport(data);
      const suffix = push.ok ? " · synced" : " · local only";
      setBtnState(btn, "success", `Saved — ${total} in library${suffix}`);
    } catch (e) {
      setBtnState(btn, "error", `Error: ${e.message || "save failed"}`);
    }
  }

  // AliExpress doesn't have a single stable buy-box id. Try a handful of
  // known anchors; fall back to body so the button at least shows up.
  function inject() {
    if (document.getElementById("droply-import-btn")) return;
    const target =
      document.querySelector("[class*='Product_buyboxButton']") ||
      document.querySelector("[class*='ProductActionPanel']") ||
      document.querySelector("[class*='product-action']") ||
      document.querySelector(".buynow-area") ||
      document.querySelector("[class*='priceArea']") ||
      document.querySelector("[data-pl='product-price']") ||
      document.body;
    if (!target) return;
    const btn = makeButton();
    btn.addEventListener("click", () => onClick(btn));
    target.insertBefore(btn, target.firstChild);
  }

  inject();
  const obs = new MutationObserver(() => inject());
  obs.observe(document.body, { childList: true, subtree: true });
})();

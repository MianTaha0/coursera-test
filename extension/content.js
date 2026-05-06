// Droply — Amazon product scraper + "Save product" injector.
// Stores captured products in chrome.storage.local (always) and best-effort
// pushes them to the dashboard backend so the website can show them.
(() => {
  const MAX_STORED = 200;
  const BACKEND_URL_KEY = "droply_backend_url";
  const DEFAULT_BACKEND = "http://localhost:8000";

  // ---------- DOM helpers ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");

  // ---------- Scraper ----------
  function extractAsin() {
    const m = location.pathname.match(/(?:\/dp\/|\/gp\/product\/)([A-Z0-9]{10})/i);
    if (m) return m[1].toUpperCase();
    const meta =
      $('input#ASIN') ||
      $('input[name="ASIN"]') ||
      $('div[data-asin]:not([data-asin=""])');
    if (meta) return (meta.value || meta.getAttribute("data-asin") || "").toUpperCase();
    return null;
  }
  function extractTitle() {
    return text($("#productTitle")) || text($("h1#title"));
  }
  function parsePrice(str) {
    if (!str) return null;
    let s = str.replace(/[^\d.,]/g, "");
    if (!s) return null;
    const lastComma = s.lastIndexOf(",");
    const lastDot = s.lastIndexOf(".");
    if (lastComma > -1 && lastDot > -1) {
      // Whichever appears last is the decimal separator.
      if (lastComma > lastDot) {
        s = s.replace(/\./g, "").replace(",", "."); // EU: 1.234,56
      } else {
        s = s.replace(/,/g, "");                    // US: 1,234.56
      }
    } else if (lastComma > -1) {
      const after = s.length - lastComma - 1;
      s = after === 2 ? s.replace(",", ".") : s.replace(/,/g, "");
    }
    const n = parseFloat(s);
    return isFinite(n) ? n : null;
  }
  function extractPrice() {
    const candidates = [
      "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
      "#corePrice_feature_div .a-price .a-offscreen",
      "#apex_desktop .a-price .a-offscreen",
      "#priceblock_ourprice",
      "#priceblock_dealprice",
      "#priceblock_saleprice",
      ".a-price .a-offscreen",
    ];
    for (const sel of candidates) {
      const el = $(sel);
      if (el) {
        const p = parsePrice(text(el));
        if (p && p > 0) return p;
      }
    }
    const whole = $(".a-price .a-price-whole");
    const frac = $(".a-price .a-price-fraction");
    if (whole) {
      const p = parsePrice(`${text(whole)}.${text(frac) || "0"}`);
      if (p) return p;
    }
    return null;
  }
  function extractCurrency() {
    // 1) Read the price-symbol element. May be "$", "£", "€", or a 3-letter
    //    code like "PKR" / "CAD" / "JPY" when Amazon shows a localized price
    //    for a non-default delivery destination.
    const symEl = text($(".a-price-symbol"));
    const symMap = {
      "$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY",
      "₹": "INR", "₽": "RUB", "₩": "KRW", "₺": "TRY",
      "R$": "BRL", "kr": "SEK", "zł": "PLN", "Kč": "CZK",
    };
    if (symMap[symEl]) return symMap[symEl];
    // 3-letter ISO code (PKR, CAD, AUD, MXN, AED, SAR, ...)
    const iso = symEl.match(/^[A-Z]{3}$/);
    if (iso) return iso[0];

    // 2) Scan the visible price text for a leading 3-letter currency code.
    const priceText = text($(".a-price .a-offscreen")) || text($(".a-price"));
    const m = priceText.match(/\b([A-Z]{3})\b/);
    if (m) return m[1];

    // 3) Hostname-based fallbacks.
    if (location.hostname.endsWith(".co.uk")) return "GBP";
    if (location.hostname.endsWith(".de") || location.hostname.endsWith(".fr") ||
        location.hostname.endsWith(".it") || location.hostname.endsWith(".es")) return "EUR";
    if (location.hostname.endsWith(".com")) return "USD";
    return "USD";
  }
  function extractImages() {
    const urls = new Set();
    $$("#altImages img").forEach((img) => {
      const src = img.getAttribute("src") || "";
      if (src) urls.add(src.replace(/\._[A-Z0-9_,]+_\./, "."));
    });
    const main = $("#imgTagWrapperId img") || $("#landingImage");
    if (main) {
      const dyn = main.getAttribute("data-a-dynamic-image");
      if (dyn) {
        try { Object.keys(JSON.parse(dyn)).forEach((u) => urls.add(u)); } catch {}
      }
      const src = main.getAttribute("src");
      if (src) urls.add(src);
    }
    return Array.from(urls).filter((u) => /^https?:\/\//.test(u)).slice(0, 12);
  }
  function extractDescription() {
    const bullets = $$("#feature-bullets li:not(.aok-hidden) span.a-list-item")
      .map((el) => text(el))
      .filter(Boolean);
    if (bullets.length) return bullets.map((b) => `• ${b}`).join("\n");
    const desc = $("#productDescription") || $("#productDescription_feature_div");
    return text(desc);
  }
  function extractStock() {
    const av = text($("#availability") || $("#availability span"));
    if (!av) return "in_stock";
    if (/(out of stock|currently unavailable|non disponibile|nicht verfügbar|no disponible|épuisé)/i.test(av)) {
      return "out_of_stock";
    }
    return "in_stock";
  }
  function extractBrand() {
    const byline = text($("#bylineInfo"));
    if (byline) return byline.replace(/^visit the |^brand:\s*/i, "").replace(/ store$/i, "");
    return "";
  }
  function scrape() {
    const asin = extractAsin();
    if (!asin) return null;
    return {
      id: `${asin}-${Date.now()}`,
      asin,
      title: extractTitle(),
      price: extractPrice(),
      currency: extractCurrency(),
      images: extractImages(),
      description: extractDescription(),
      stock_status: extractStock(),
      brand: extractBrand(),
      amazon_url: `${location.origin}/dp/${asin}`,
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

  async function saveImport(item) {
    const total = await saveLocal(item);
    const push = await pushToBackend(item);
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

  function inject() {
    if (document.getElementById("droply-import-btn")) return;
    const target =
      document.getElementById("buybox") ||
      document.getElementById("rightCol") ||
      document.getElementById("addToCart_feature_div") ||
      document.getElementById("desktop_buybox") ||
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

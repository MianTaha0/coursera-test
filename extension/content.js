// Droply — Amazon product scraper + "Save product" injector.
// Self-contained: no backend, no login. Stores captured products in chrome.storage.local.
(() => {
  const MAX_STORED = 200;

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
    const cleaned = str.replace(/[^\d.,]/g, "").replace(/\.(?=\d{3}\b)/g, "");
    const n = parseFloat(cleaned.replace(",", "."));
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
    const sym = text($(".a-price-symbol"));
    const map = { "$": "USD", "£": "GBP", "€": "EUR" };
    if (map[sym]) return map[sym];
    if (location.hostname.endsWith(".co.uk")) return "GBP";
    if (location.hostname.endsWith(".com")) return "USD";
    return "EUR";
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
  function saveImport(item) {
    return new Promise((resolve, reject) => {
      chrome.storage.local.get(["droply_imports", "droply_today"], (res) => {
        const imports = Array.isArray(res.droply_imports) ? res.droply_imports : [];
        // Replace any earlier entry for the same ASIN, then prepend.
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
      const total = await saveImport(data);
      setBtnState(btn, "success", `Saved — ${total} in library`);
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

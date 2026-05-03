// Droply — Amazon product page scraper + "Import to eBay" injector.
(() => {
  const CONFIG = {
    API_URL: "http://localhost:8000",
    APP_URL: "http://localhost:3000",
  };

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
    const normalized = cleaned.replace(",", ".");
    const n = parseFloat(normalized);
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
      if (src) {
        // Amazon thumbs use _SS40_, _SX38_ etc — strip to get hi-res variant.
        urls.add(src.replace(/\._[A-Z0-9_,]+_\./, "."));
      }
    });
    const main = $("#imgTagWrapperId img") || $("#landingImage");
    if (main) {
      const dyn = main.getAttribute("data-a-dynamic-image");
      if (dyn) {
        try {
          Object.keys(JSON.parse(dyn)).forEach((u) => urls.add(u));
        } catch {}
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
    const lower = av.toLowerCase();
    if (/(out of stock|currently unavailable|non disponibile|nicht verfügbar|no disponible|épuisé)/i.test(lower)) {
      return "out_of_stock";
    }
    return "in_stock";
  }

  function extractBrand() {
    const byline = text($("#bylineInfo"));
    if (byline) return byline.replace(/^visit the |^brand:\s*/i, "").replace(/ store$/i, "");
    const tr = $$("#productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr");
    for (const row of tr) {
      const k = text($("th, td:first-child", row)).toLowerCase();
      if (k.includes("brand")) {
        return text($("td:last-child", row));
      }
    }
    return "";
  }

  function scrape() {
    const asin = extractAsin();
    if (!asin) return null;
    return {
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
    };
  }

  // ---------- Auth ----------
  function getToken() {
    return new Promise((resolve) => {
      chrome.storage.local.get(["droply_token"], (res) => resolve(res.droply_token || null));
    });
  }

  // ---------- Button injector ----------
  function makeButton() {
    const btn = document.createElement("button");
    btn.id = "droply-import-btn";
    btn.type = "button";
    btn.textContent = "Import to eBay";
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
    btn.addEventListener("mouseenter", () => (btn.style.background = "#16a34a"));
    btn.addEventListener("mouseleave", () => {
      if (!btn.dataset.locked) btn.style.background = "#22c55e";
    });
    return btn;
  }

  function setBtnState(btn, state, label) {
    btn.dataset.locked = state === "loading" || state === "success" || state === "error" ? "1" : "";
    btn.disabled = state === "loading";
    btn.textContent = label;
    if (state === "loading") {
      btn.style.background = "#6b7280";
      btn.textContent = "⏳ Importing…";
    } else if (state === "success") {
      btn.style.background = "#16a34a";
    } else if (state === "error") {
      btn.style.background = "#dc2626";
      btn.style.color = "#fff";
    } else {
      btn.style.background = "#22c55e";
    }
  }

  async function onClick(btn) {
    setBtnState(btn, "loading", "");
    const token = await getToken();
    if (!token) {
      setBtnState(btn, "error", `Please login at ${CONFIG.APP_URL}`);
      return;
    }
    const data = scrape();
    if (!data || !data.asin) {
      setBtnState(btn, "error", "Could not read product data");
      return;
    }
    try {
      const resp = await fetch(`${CONFIG.API_URL}/api/import-product`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(data),
      });
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const msg = json.detail || json.error || `HTTP ${resp.status}`;
        setBtnState(btn, "error", `❌ ${msg}`);
        return;
      }
      setBtnState(btn, "success", "✓ Imported successfully");
      // Track count for popup
      chrome.storage.local.get(["droply_today"], (res) => {
        const today = new Date().toISOString().slice(0, 10);
        const t = res.droply_today && res.droply_today.date === today
          ? res.droply_today
          : { date: today, count: 0 };
        t.count += 1;
        chrome.storage.local.set({ droply_today: t });
      });
    } catch (e) {
      setBtnState(btn, "error", `❌ ${e.message || "Network error"}`);
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
    // Place near the buy box top.
    target.insertBefore(btn, target.firstChild);
  }

  // Re-run on dynamic Amazon page updates.
  inject();
  const obs = new MutationObserver(() => inject());
  obs.observe(document.body, { childList: true, subtree: true });
})();

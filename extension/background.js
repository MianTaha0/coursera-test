// Droply background service worker — periodic re-check of saved products.
//
// Strategy: open each saved Amazon URL in a hidden background tab. The
// content script runs automatically on document_idle, scrapes the page,
// and pushes the latest price/stock to chrome.storage + the backend
// (which records a snapshot in price_history when anything changes).
// We close the tab as soon as the content script confirms it's done.

const ALARM_NAME = "droply-recheck-all";
const RECHECK_INTERVAL_KEY = "droply_recheck_interval_min"; // user-configurable
const DEFAULT_INTERVAL_MIN = 360; // 6 hours
const TAB_TIMEOUT_MS = 25_000;     // safety: never let a recheck tab linger
const RECHECK_RUNNING_KEY = "droply_recheck_running";
const LAST_RECHECK_KEY = "droply_last_recheck_at";

// ---------- Alarm setup ----------
async function setupAlarm() {
  const { [RECHECK_INTERVAL_KEY]: interval } = await chrome.storage.local.get([RECHECK_INTERVAL_KEY]);
  const minutes = Math.max(15, Number(interval) || DEFAULT_INTERVAL_MIN);
  chrome.alarms.create(ALARM_NAME, {
    delayInMinutes: minutes,
    periodInMinutes: minutes,
  });
}

chrome.runtime.onInstalled.addListener(setupAlarm);
chrome.runtime.onStartup.addListener(setupAlarm);

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === ALARM_NAME) await recheckAll({ source: "alarm" });
});

// ---------- Message channel from popup ----------
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "DROPLY_RECHECK_NOW") {
    recheckAll({ source: "manual" }).then(
      (result) => sendResponse({ ok: true, ...result }),
      (err) => sendResponse({ ok: false, error: String(err) }),
    );
    return true; // async response
  }
  if (msg?.type === "DROPLY_RECHECK_DONE" && _sender.tab?.id) {
    // Content script tells us a recheck-tab is done.
    chrome.tabs.remove(_sender.tab.id).catch(() => {});
  }
  if (msg?.type === "DROPLY_RECHECK_STATUS") {
    chrome.storage.local.get([RECHECK_RUNNING_KEY, LAST_RECHECK_KEY], (res) => {
      sendResponse({
        running: !!res[RECHECK_RUNNING_KEY],
        last_at: res[LAST_RECHECK_KEY] || null,
      });
    });
    return true;
  }
});

// ---------- Recheck driver ----------
async function recheckAll({ source }) {
  const { droply_imports = [] } = await chrome.storage.local.get(["droply_imports"]);
  const targets = droply_imports.filter((p) => p.amazon_url);
  if (!targets.length) return { count: 0, source };

  await chrome.storage.local.set({ [RECHECK_RUNNING_KEY]: true });
  let processed = 0;
  try {
    for (const item of targets) {
      try {
        await rescanInBackgroundTab(item.amazon_url);
        processed++;
      } catch (e) {
        console.warn("Droply recheck failed for", item.asin, e);
      }
      // Politeness pause so we don't hammer Amazon
      await sleep(2_000);
    }
  } finally {
    await chrome.storage.local.set({
      [RECHECK_RUNNING_KEY]: false,
      [LAST_RECHECK_KEY]: new Date().toISOString(),
    });
  }
  return { count: processed, source };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function rescanInBackgroundTab(url) {
  return new Promise((resolve, reject) => {
    chrome.tabs.create({ url, active: false }, (tab) => {
      if (chrome.runtime.lastError || !tab?.id) {
        return reject(chrome.runtime.lastError || new Error("no tab"));
      }
      const tabId = tab.id;
      let done = false;
      const finish = (ok, err) => {
        if (done) return;
        done = true;
        chrome.tabs.onUpdated.removeListener(updateListener);
        chrome.tabs.remove(tabId).catch(() => {});
        clearTimeout(timer);
        ok ? resolve() : reject(err);
      };
      const updateListener = (id, changeInfo) => {
        if (id !== tabId) return;
        if (changeInfo.status === "complete") {
          // Give the content script ~6s to scrape + push to backend
          setTimeout(() => finish(true), 6_000);
        }
      };
      chrome.tabs.onUpdated.addListener(updateListener);
      const timer = setTimeout(
        () => finish(false, new Error("recheck tab timeout")),
        TAB_TIMEOUT_MS,
      );
    });
  });
}

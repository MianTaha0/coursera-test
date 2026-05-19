// Droply background service worker — periodic re-check of saved products.
//
// Strategy: open each saved Amazon URL in a hidden background tab. The
// content script runs automatically on document_idle, scrapes the page,
// and pushes the latest price/stock to chrome.storage + the backend
// (which records a snapshot in price_history when anything changes).
// We close the tab as soon as the content script confirms it's done.

const ALARM_NAME = "droply-recheck-all";
const RETRY_ALARM_NAME = "droply-retry-flush";
const RETRY_QUEUE_KEY = "droply_retry_queue";
const BACKEND_URL_KEY = "droply_backend_url";
const DEFAULT_BACKEND = "http://localhost:8000";
const RETRY_FLUSH_INTERVAL_MIN = 10;
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
  // Retry-queue flush — fires on a fast cadence so backend recovery is quick.
  chrome.alarms.create(RETRY_ALARM_NAME, {
    delayInMinutes: 1,
    periodInMinutes: RETRY_FLUSH_INTERVAL_MIN,
  });
}

chrome.runtime.onInstalled.addListener(setupAlarm);
chrome.runtime.onStartup.addListener(setupAlarm);

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === ALARM_NAME) await recheckAll({ source: "alarm" });
  if (alarm.name === RETRY_ALARM_NAME) await flushRetryQueue("alarm");
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
  if (msg?.type === "DROPLY_RETRY_NUDGE") {
    // Content script saw a failed POST and queued it; surface a toast and try
    // to flush soon. We don't await here — the channel is fire-and-forget.
    notifyBackendDown();
    flushRetryQueue("nudge").catch((e) => console.warn("retry flush failed", e));
  }
  if (msg?.type === "DROPLY_RETRY_FLUSH") {
    flushRetryQueue("manual").then(
      (result) => sendResponse({ ok: true, ...result }),
      (err) => sendResponse({ ok: false, error: String(err) }),
    );
    return true;
  }
});

// ---------- Retry queue ----------
async function getBackendUrl() {
  const { [BACKEND_URL_KEY]: u } = await chrome.storage.local.get([BACKEND_URL_KEY]);
  return u || DEFAULT_BACKEND;
}

let notifyDownRecentMs = 0;
async function notifyBackendDown() {
  // Throttle — only one toast every 60s.
  if (Date.now() - notifyDownRecentMs < 60_000) return;
  notifyDownRecentMs = Date.now();
  try {
    await chrome.notifications.create("droply-backend-down", {
      type: "basic",
      iconUrl: "icons/icon-128.png",
      title: "Droply — backend unreachable",
      message: "Saved locally. We'll retry the sync automatically when the backend comes back.",
    });
  } catch (_) { /* notifications may be disabled */ }
}

async function flushRetryQueue(source) {
  const { [RETRY_QUEUE_KEY]: queue = [] } = await chrome.storage.local.get([RETRY_QUEUE_KEY]);
  if (!queue.length) return { source, drained: 0, remaining: 0 };
  const url = await getBackendUrl();
  if (!url) return { source, drained: 0, remaining: queue.length };

  const remaining = [];
  let drained = 0;
  for (const item of queue) {
    try {
      const r = await fetch(`${url}/api/products`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item),
      });
      if (r.ok) drained++;
      else remaining.push(item);
    } catch (_) {
      remaining.push(item);
    }
  }
  await chrome.storage.local.set({ [RETRY_QUEUE_KEY]: remaining });
  if (drained > 0) {
    try {
      await chrome.notifications.create(`droply-drained-${Date.now()}`, {
        type: "basic",
        iconUrl: "icons/icon-128.png",
        title: "Droply — sync caught up",
        message: `Pushed ${drained} pending product${drained === 1 ? "" : "s"} to the backend.`,
      });
    } catch (_) { /* swallow */ }
  }
  return { source, drained, remaining: remaining.length };
}

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
    // Open the recheck page in a brand-new minimized window so it stays out
    // of the user's tab strip and never steals focus.
    chrome.windows.create(
      { url, focused: false, state: "minimized", type: "normal" },
      (win) => {
        if (chrome.runtime.lastError || !win || !win.tabs?.[0]?.id) {
          return reject(chrome.runtime.lastError || new Error("no window"));
        }
        const tabId = win.tabs[0].id;
        const winId = win.id;
        let done = false;
        const finish = (ok, err) => {
          if (done) return;
          done = true;
          chrome.tabs.onUpdated.removeListener(updateListener);
          // Closing the only tab in the window auto-closes the window too.
          if (winId !== undefined) {
            chrome.windows.remove(winId).catch(() => {
              chrome.tabs.remove(tabId).catch(() => {});
            });
          } else {
            chrome.tabs.remove(tabId).catch(() => {});
          }
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
      },
    );
  });
}

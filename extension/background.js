const API = "http://127.0.0.1:27420";
const MAX_BUFFER = 100;

let connected = false;
let buffer = [];

// ── Send event to agent ────────────────────────────────────────────────────

async function sendEvent(url, title) {
  // Skip chrome:// and extension pages
  if (!url || url.startsWith("chrome://") || url.startsWith("chrome-extension://")) return;

  const payload = { url, title, timestamp: Date.now() };

  if (!connected) {
    if (buffer.length < MAX_BUFFER) buffer.push(payload);
    return;
  }

  try {
    const res = await fetch(`${API}/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    if (!connected) {
      connected = true;
      updateIcon(true);
    }
    // Flush buffer
    flushBuffer();
  } catch {
    connected = false;
    updateIcon(false);
    if (buffer.length < MAX_BUFFER) buffer.push(payload);
  }
}

async function flushBuffer() {
  while (buffer.length > 0) {
    const item = buffer[0];
    try {
      const res = await fetch(`${API}/event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item),
      });
      if (!res.ok) break;
      buffer.shift();
    } catch {
      break;
    }
  }
}

// ── Connection health check ────────────────────────────────────────────────

async function checkConnection() {
  try {
    const res = await fetch(`${API}/status`, { signal: AbortSignal.timeout(2000) });
    if (res.ok) {
      if (!connected) {
        connected = true;
        updateIcon(true);
        flushBuffer();
      }
    } else {
      throw new Error();
    }
  } catch {
    if (connected) {
      connected = false;
      updateIcon(false);
    }
  }
}

// Check every 30s
setInterval(checkConnection, 30000);
checkConnection();

// ── Icon helpers ───────────────────────────────────────────────────────────

function updateIcon(isConnected) {
  chrome.action.setIcon({
    path: isConnected ? "icons/icon48.png" : "icons/icon48_grey.png",
  });
  chrome.action.setTitle({
    title: isConnected ? "PC Activity Tracker — подключён" : "PC Activity Tracker — нет связи с агентом",
  });
}

// ── Tab event listeners ────────────────────────────────────────────────────

chrome.tabs.onActivated.addListener(async (info) => {
  const tab = await chrome.tabs.get(info.tabId);
  sendEvent(tab.url, tab.title);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.active) {
    sendEvent(tab.url, tab.title);
  }
});

// Cache per-assistant-message metrics in localStorage so they persist across navigation/reload.
const KEY = "msgMetrics:v1";

type Stored = Record<string, { runJson?: any | null; flat?: any | null }>;

function loadAll(): Stored {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Stored) : {};
  } catch {
    return {};
  }
}

function saveAll(obj: Stored) {
  try {
    localStorage.setItem(KEY, JSON.stringify(obj));
  } catch {
    /* ignore quota errors */
  }
}

export function setMsgMetrics(messageId: string, data: { runJson?: any | null; flat?: any | null }) {
  const all = loadAll();
  const cur = all[messageId] || {};
  all[messageId] = {
    runJson: data.runJson ?? cur.runJson ?? null,
    flat: data.flat ?? cur.flat ?? null,
  };
  saveAll(all);
}

export function getMsgMetrics(messageId: string) {
  const all = loadAll();
  return all[messageId] || null;
}

export function clearMsgMetrics(messageId: string) {
  const all = loadAll();
  if (all[messageId]) {
    delete all[messageId];
    saveAll(all);
  }
}

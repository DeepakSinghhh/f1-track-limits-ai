const DEFAULT_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const STORAGE_KEY = "apex_console_api_base_url";

export function getApiBaseUrl() {
  return localStorage.getItem(STORAGE_KEY) || DEFAULT_BASE_URL;
}

export function setApiBaseUrl(url) {
  localStorage.setItem(STORAGE_KEY, url);
}

async function request(path, options = {}) {
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${body ? `: ${body}` : ""}`);
  }
  return res.json();
}

export const fetchHealth = () => request("/health");
export const fetchQueue = () => request("/queue");
export const fetchOverrides = () => request("/overrides");

export const confirmItem = (eventId, { stewardId, sessionType, rationale }) =>
  request(`/queue/${eventId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ steward_id: stewardId, session_type: sessionType, rationale }),
  });

export const rejectItem = (eventId, { stewardId, rationale }) =>
  request(`/queue/${eventId}/reject`, {
    method: "POST",
    body: JSON.stringify({ steward_id: stewardId, rationale }),
  });

/** Connects to /ws/queue. onMessage receives the parsed frame
 * ({type: "snapshot"|"new_item"|"decision", ...}). Returns the WebSocket
 * so the caller can close it on unmount.
 */
export function connectQueueSocket(onMessage, onStatusChange) {
  const wsUrl = getApiBaseUrl().replace(/^http/, "ws") + "/ws/queue";
  const ws = new WebSocket(wsUrl);
  ws.onopen = () => onStatusChange?.("connected");
  ws.onclose = () => onStatusChange?.("disconnected");
  ws.onerror = () => onStatusChange?.("error");
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      // malformed frame -- ignore rather than crash the console
    }
  };
  return ws;
}

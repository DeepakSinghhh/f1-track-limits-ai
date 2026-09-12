import { useEffect, useMemo, useRef, useState } from "react";
import {
  confirmItem,
  connectQueueSocket,
  fetchHealth,
  fetchOverrides,
  fetchQueue,
  getApiBaseUrl,
  rejectItem,
  setApiBaseUrl,
} from "./api";
import StewardItemCard from "./components/StewardItemCard";
import DriftIndicator from "./components/DriftIndicator";

const SESSION_TYPES = ["practice", "qualifying", "sprint", "race"];

export default function App() {
  const [items, setItems] = useState([]);
  const [decisions, setDecisions] = useState({});
  const [overrides, setOverrides] = useState([]);
  const [health, setHealth] = useState(null);
  const [wsStatus, setWsStatus] = useState("connecting");
  const [stewardId, setStewardId] = useState("");
  const [sessionType, setSessionType] = useState("race");
  const [apiBaseUrl, setApiBaseUrlState] = useState(getApiBaseUrl());
  const wsRef = useRef(null);

  const refreshOverrides = async () => {
    try {
      setOverrides(await fetchOverrides());
    } catch {
      // best-effort -- the drift banner just stays stale until the next poll
    }
  };

  useEffect(() => {
    let cancelled = false;

    fetchHealth()
      .then((h) => !cancelled && setHealth(h))
      .catch(() => !cancelled && setHealth(null));

    fetchQueue()
      .then((q) => !cancelled && setItems(q))
      .catch(() => {});

    refreshOverrides();

    const ws = connectQueueSocket((frame) => {
      if (frame.type === "snapshot") {
        setItems(frame.items);
      } else if (frame.type === "new_item") {
        setItems((prev) => {
          const next = prev.filter((it) => it.finding.event_id !== frame.item.finding.event_id);
          next.push(frame.item);
          return next.sort((a, b) => b.priority - a.priority);
        });
      } else if (frame.type === "decision") {
        setDecisions((prev) => ({ ...prev, [frame.event_id]: frame.decision }));
        refreshOverrides();
      }
    }, setWsStatus);
    wsRef.current = ws;

    return () => {
      cancelled = true;
      ws.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBaseUrl]);

  const sortedItems = useMemo(
    () => [...items].sort((a, b) => b.priority - a.priority),
    [items]
  );

  const handleApiBaseUrlChange = (e) => {
    const url = e.target.value;
    setApiBaseUrlState(url);
    setApiBaseUrl(url);
  };

  const handleConfirm = async (eventId, opts) => {
    const result = await confirmItem(eventId, opts);
    setDecisions((prev) => ({ ...prev, [eventId]: "violation" }));
    refreshOverrides();
    return result;
  };

  const handleReject = async (eventId, opts) => {
    const result = await rejectItem(eventId, opts);
    setDecisions((prev) => ({ ...prev, [eventId]: "no_violation" }));
    refreshOverrides();
    return result;
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title">
          <h1>Apex Assist</h1>
          <span className="circuit">
            {health ? `${health.circuit} · ${health.year} · agent ${health.agent_enabled ? "on" : "off"}` : "connecting…"}
          </span>
        </div>
        <span className="conn-status">
          <span className="conn-dot" data-status={wsStatus} />
          {wsStatus}
        </span>
      </header>

      <div className="toolbar">
        <div className="field">
          <label htmlFor="steward-id">Steward ID</label>
          <input
            id="steward-id"
            value={stewardId}
            onChange={(e) => setStewardId(e.target.value)}
            placeholder="e.g. steward-1"
          />
        </div>
        <div className="field">
          <label htmlFor="session-type">Session type</label>
          <select id="session-type" value={sessionType} onChange={(e) => setSessionType(e.target.value)}>
            {SESSION_TYPES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="api-base-url">API base URL</label>
          <input id="api-base-url" value={apiBaseUrl} onChange={handleApiBaseUrlChange} />
        </div>
      </div>

      <DriftIndicator overrides={overrides} />

      <main className="queue">
        {sortedItems.length === 0 && (
          <div className="empty-state">No findings in the queue yet.</div>
        )}
        {sortedItems.map((item) => (
          <StewardItemCard
            key={item.finding.event_id}
            item={item}
            decision={decisions[item.finding.event_id]}
            reviewProps={{
              stewardId,
              sessionType,
              onConfirm: handleConfirm,
              onReject: handleReject,
            }}
          />
        ))}
      </main>
    </div>
  );
}

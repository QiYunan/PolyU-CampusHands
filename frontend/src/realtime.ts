import { useCallback, useEffect, useRef, useState } from "react";

export type RealtimeNotice = {
  version: 1;
  event_id: number;
  event_type: string;
  resource_kind: "request" | "offer";
  resource_id: number;
  status: string;
  public_message: string;
  created_at: string;
};

export type ConnectionMode = "live" | "polling";

export function noticeFromJson(value: string): RealtimeNotice | null {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed !== "object" || parsed === null) return null;
    const item = parsed as Record<string, unknown>;
    if (item.version !== 1 || !Number.isSafeInteger(item.event_id) || Number(item.event_id) <= 0 ||
      (item.resource_kind !== "request" && item.resource_kind !== "offer") ||
      !Number.isSafeInteger(item.resource_id) || Number(item.resource_id) <= 0 ||
      typeof item.event_type !== "string" || typeof item.status !== "string" ||
      typeof item.public_message !== "string" || typeof item.created_at !== "string" ||
      Number.isNaN(Date.parse(item.created_at))) return null;
    return item as RealtimeNotice;
  } catch {
    return null;
  }
}

function socketUrl(kind: "request" | "helper", id: number, actorId: number): string {
  const path = kind === "request" ? `/ws/requests/${id}` : `/ws/helpers/${id}/offers`;
  const url = new URL(path, window.location.href);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("demo_user_id", String(actorId));
  return url.toString();
}

export function useRealtimeSnapshot<T>({ kind, id, actorId, load, onSnapshot, onError, snapshotEventId }: {
  kind: "request" | "helper";
  id: number | null;
  actorId: number;
  load: () => Promise<T>;
  onSnapshot: (snapshot: T) => void;
  onError: (error: string) => void;
  snapshotEventId?: (snapshot: T) => number;
}) {
  const [mode, setMode] = useState<ConnectionMode>("polling");
  const callbacks = useRef({ load, onSnapshot, onError, snapshotEventId });
  callbacks.current = { load, onSnapshot, onError, snapshotEventId };
  const refreshRef = useRef<() => Promise<void>>(async () => undefined);
  const applyRef = useRef<(snapshot: T) => void>(() => undefined);

  useEffect(() => {
    if (id === null || !Number.isSafeInteger(id) || id <= 0) return;
    const targetId = id;
    let active = true;
    let dirty = false;
    let inFlight: Promise<void> | null = null;
    let generation = 0;
    let lastEventId = 0;
    let lastRefreshSucceeded = false;
    let socket: WebSocket | null = null;
    let pollTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let attempts = 0;

    function apply(snapshot: T) {
      generation += 1; // An older GET result may not overwrite this snapshot.
      lastRefreshSucceeded = true;
      callbacks.current.onSnapshot(snapshot);
      lastEventId = Math.max(lastEventId, callbacks.current.snapshotEventId?.(snapshot) ?? 0);
      callbacks.current.onError("");
    }

    function refresh(): Promise<void> {
      dirty = true;
      if (inFlight) return inFlight;
      inFlight = (async () => {
        while (active && dirty) {
          dirty = false;
          const token = ++generation;
          try {
            const snapshot = await callbacks.current.load();
            if (active && token === generation) {
              lastRefreshSucceeded = true;
              callbacks.current.onSnapshot(snapshot);
              lastEventId = Math.max(lastEventId, callbacks.current.snapshotEventId?.(snapshot) ?? 0);
              callbacks.current.onError("");
              if (socket?.readyState === 1) {
                stopPolling();
                setMode("live");
              }
            }
          } catch (cause) {
            if (active && token === generation) {
              lastRefreshSucceeded = false;
              callbacks.current.onError(cause instanceof Error ? cause.message : "读取失败");
              startPolling();
              setMode("polling");
            }
          }
        }
      })().finally(() => {
        inFlight = null;
        if (active && dirty) void refresh();
      });
      return inFlight;
    }

    function startPolling() {
      if (pollTimer === null) pollTimer = window.setInterval(() => { void refresh(); }, 2000);
    }

    function stopPolling() {
      if (pollTimer !== null) window.clearInterval(pollTimer);
      pollTimer = null;
    }

    function reconnect() {
      if (!active || reconnectTimer !== null) return;
      const delay = Math.min(1000 * 2 ** Math.min(attempts, 5), 30000);
      attempts += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    }

    function connect() {
      if (!active) return;
      try {
        socket = new WebSocket(socketUrl(kind, targetId, actorId));
      } catch {
        reconnect();
        return;
      }
      const current = socket;
      current.onopen = () => {
        attempts = 0;
        // This second GET closes the initial GET-to-subscribe race.
        void refresh().then(() => {
          if (active && lastRefreshSucceeded && socket === current && current.readyState === 1) {
            stopPolling();
            setMode("live");
          }
        });
      };
      current.onmessage = (event: MessageEvent) => {
        const notice = typeof event.data === "string" ? noticeFromJson(event.data) : null;
        if (!notice || (kind === "request" && (notice.resource_kind !== "request" || notice.resource_id !== targetId)) ||
          (kind === "helper" && notice.resource_kind !== "offer")) {
          current.close(1003);
          return;
        }
        if (notice.event_id <= lastEventId) return;
        lastEventId = notice.event_id;
        void refresh();
      };
      current.onerror = () => current.close();
      current.onclose = () => {
        if (!active || socket !== current) return;
        socket = null;
        setMode("polling");
        startPolling();
        void refresh();
        reconnect();
      };
    }

    refreshRef.current = refresh;
    applyRef.current = apply;
    setMode("polling");
    startPolling();
    void refresh().then(() => { if (active) connect(); });
    return () => {
      active = false;
      refreshRef.current = async () => undefined;
      applyRef.current = () => undefined;
      stopPolling();
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (socket !== null) {
        socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
        socket.close();
      }
    };
  }, [kind, id, actorId]);

  const refresh = useCallback(() => refreshRef.current(), []);
  const applyAuthoritative = useCallback((snapshot: T) => applyRef.current(snapshot), []);
  return { mode, refresh, applyAuthoritative };
}

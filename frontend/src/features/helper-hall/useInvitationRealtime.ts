import { useEffect, useRef, useState } from "react";

export type InvitationConnectionMode = "live" | "polling";

function invitationSocketUrl(helperId: number): string {
  const url = new URL(`/ws/helpers/${helperId}/invitations`, window.location.href);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("demo_user_id", String(helperId));
  return url.toString();
}

function isInvitationNotice(raw: unknown, helperId: number): boolean {
  if (typeof raw !== "object" || raw === null) return false;
  const value = raw as Record<string, unknown>;
  return value.version === 1 && value.resource_kind === "invitation" && value.resource_id === helperId;
}

export function useInvitationRealtime(helperId: number, refresh: () => Promise<void>) {
  const [mode, setMode] = useState<InvitationConnectionMode>("polling");
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    let active = true;
    let socket: WebSocket | null = null;
    let pollTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let attempts = 0;

    const startPolling = () => {
      if (pollTimer === null) pollTimer = window.setInterval(() => { void refreshRef.current(); }, 2000);
      setMode("polling");
    };
    const stopPolling = () => {
      if (pollTimer !== null) window.clearInterval(pollTimer);
      pollTimer = null;
    };
    const reconnect = () => {
      if (!active || reconnectTimer !== null) return;
      const delay = Math.min(1000 * 2 ** Math.min(attempts, 5), 30000);
      attempts += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };
    const connect = () => {
      if (!active) return;
      try {
        socket = new WebSocket(invitationSocketUrl(helperId));
      } catch {
        startPolling();
        reconnect();
        return;
      }
      const current = socket;
      current.onopen = () => {
        attempts = 0;
        void refreshRef.current().then(() => {
          if (active && socket === current && current.readyState === WebSocket.OPEN) {
            stopPolling();
            setMode("live");
          }
        });
      };
      current.onmessage = (event) => {
        try {
          if (typeof event.data === "string" && isInvitationNotice(JSON.parse(event.data), helperId)) {
            void refreshRef.current();
          }
        } catch {
          // Invalid notifications are ignored; the next GET or poll remains authoritative.
        }
      };
      current.onclose = () => {
        if (socket === current) socket = null;
        startPolling();
        reconnect();
      };
      current.onerror = () => current.close();
    };

    void refreshRef.current();
    startPolling();
    connect();
    return () => {
      active = false;
      stopPolling();
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [helperId]);

  return mode;
}

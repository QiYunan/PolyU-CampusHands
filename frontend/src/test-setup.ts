import "@testing-library/jest-dom/vitest";
import { beforeEach, vi } from "vitest";

// Existing UI tests remain fully offline even when jsdom provides WebSocket.
beforeEach(() => {
  vi.stubGlobal("WebSocket", class {
    readyState = 0;
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: (() => void) | null = null;
    onclose: (() => void) | null = null;
    close() { this.readyState = 3; }
  });
});

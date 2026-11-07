import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { noticeFromJson } from "./realtime";


class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 0;
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  open() { this.readyState = 1; this.onopen?.(); }
  message(eventId: number, kind: "request" | "offer" = "request", resourceId = 7) {
    this.onmessage?.({ data: JSON.stringify({
      version: 1, event_id: eventId, event_type: "inbox_changed", resource_kind: kind,
      resource_id: resourceId, status: "matched", public_message: "公开更新", created_at: new Date().toISOString(),
    }) } as MessageEvent);
  }
  close() { this.readyState = 3; this.onclose?.(); }
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); FakeSocket.instances = []; });

const draft = {
  id: 7, requester_id: 1, category: "borrow", raw_text: null, item_type: "scientific_calculator",
  location: "VA", deadline: "2027-01-01T10:00:00Z", urgency: null, status: "draft",
  created_at: "2026-11-05T00:00:00Z", updated_at: "2026-11-05T00:00:00Z", events: [],
};
const matched = { ...draft, status: "matched", matched_helper: "Carol", handoff_location: "VA", events: [
  { id: 2, event_type: "offer_accepted", public_message: "Carol 已接受", created_at: draft.created_at },
  { id: 1, event_type: "offer_sent", public_message: "已联系 Carol", created_at: draft.created_at },
  { id: 2, event_type: "offer_accepted", public_message: "Carol 已接受", created_at: draft.created_at },
] };

test("GET before and after subscribe closes the race; notifications reconcile without duplicate events", async () => {
  vi.stubGlobal("WebSocket", FakeSocket);
  let snapshot: typeof draft | typeof matched = draft;
  const fetchMock = vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("llm-status") ? { primary: "mock", fallback: "mock", active: null, primary_status: "unknown", fallback_status: "unknown", fallback_active: false } : snapshot }));
  const requestCalls = () => fetchMock.mock.calls.filter(([url]) => url.includes("/api/requests/")).length;
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/requests/7"]}><App /></MemoryRouter>);
  expect(await screen.findByText(/状态：草稿/)).toBeInTheDocument();
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  expect(FakeSocket.instances[0].url).toContain("/ws/requests/7?demo_user_id=1");
  snapshot = matched;
  FakeSocket.instances[0].open();
  expect(await screen.findByText(/状态：匹配成功/)).toBeInTheDocument();
  expect(screen.getByLabelText("连接状态")).toHaveTextContent("实时连接");
  expect(requestCalls()).toBe(2);
  FakeSocket.instances[0].message(2);
  await new Promise((resolve) => setTimeout(resolve, 30));
  expect(requestCalls()).toBe(2); // Already covered by the second GET.
  expect(screen.getAllByText("Carol 已接受")).toHaveLength(1);
  const events = [...screen.getByRole("list", { name: "" }).querySelectorAll("li")];
  expect(events.map((item) => item.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("已联系 Carol"), expect.stringContaining("Carol 已接受")]));
});

test("an older GET cannot overwrite a newer authoritative HTTP action response", async () => {
  vi.stubGlobal("WebSocket", FakeSocket);
  let getCount = 0;
  let resolveStale: ((value: { ok: boolean; json: () => Promise<typeof draft> }) => void) | undefined;
  const fetchMock = vi.fn((url: string) => {
    if (url.includes("llm-status")) return Promise.resolve({ ok: true, json: async () => ({ primary: "mock", fallback: "mock", active: null, primary_status: "unknown", fallback_status: "unknown", fallback_active: false }) });
    if (url.endsWith("/search")) return Promise.resolve({ ok: true, json: async () => matched });
    getCount += 1;
    if (getCount === 3) return new Promise<{ ok: boolean; json: () => Promise<typeof draft> }>((resolve) => { resolveStale = resolve; });
    return Promise.resolve({ ok: true, json: async () => draft });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/requests/7"]}><App /></MemoryRouter>);
  await screen.findByText(/状态：草稿/);
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  FakeSocket.instances[0].open();
  await waitFor(() => expect(getCount).toBe(2));
  FakeSocket.instances[0].message(1);
  await waitFor(() => expect(resolveStale).toBeDefined());
  fireEvent.click(screen.getByRole("button", { name: "开始匹配" }));
  expect(await screen.findByText(/状态：匹配成功/)).toBeInTheDocument();
  resolveStale?.({ ok: true, json: async () => draft });
  await new Promise((resolve) => setTimeout(resolve, 30));
  expect(screen.getByText(/状态：匹配成功/)).toBeInTheDocument();
});

test("Helper receives new Offer, then disconnect uses polling and role change closes socket", async () => {
  vi.stubGlobal("WebSocket", FakeSocket);
  const offer = { id: 12, request_id: 7, helper_id: 3, item_type: "scientific_calculator", item_name: "Calculator",
    location: "VA", deadline: draft.deadline, status: "pending", request_status: "awaiting_response",
    sent_at: draft.created_at, expires_at: draft.deadline, requester_confirmed: false, helper_confirmed: false };
  let offers: typeof offer[] = [];
  const fetchMock = vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("/helpers/") ? offers : draft }));
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("当前角色"), { target: { value: "3" } });
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  expect(FakeSocket.instances[0].url).toContain("/ws/helpers/3/offers?demo_user_id=3");
  FakeSocket.instances[0].open();
  await waitFor(() => expect(screen.getByLabelText("连接状态")).toHaveTextContent("实时连接"));
  offers = [offer];
  FakeSocket.instances[0].message(3, "offer", 12);
  expect(await screen.findByRole("button", { name: "接受" })).toBeInTheDocument();
  FakeSocket.instances[0].close();
  expect(await screen.findByLabelText("连接状态")).toHaveTextContent("轮询模式");
  const afterClose = fetchMock.mock.calls.length;
  await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(afterClose), { timeout: 2600 });
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(2), { timeout: 2600 });
  offers = [{ ...offer, status: "accepted", request_status: "matched" }];
  FakeSocket.instances[1].open();
  await waitFor(() => expect(screen.getByLabelText("连接状态")).toHaveTextContent("实时连接"));
  expect(screen.getByText(/accepted/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("当前角色"), { target: { value: "2" } });
  await waitFor(() => expect(FakeSocket.instances.some((socket) => socket.url.includes("/helpers/2/"))).toBe(true));
  expect(FakeSocket.instances[1].readyState).toBe(3);
});

test("invalid transport data is never rendered", () => {
  expect(noticeFromJson('{"version":1,"event_id":1,"public_message":"secret"}')).toBeNull();
  expect(noticeFromJson("not json")).toBeNull();
});

import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

const roles = [
  { id: 1, display_name: "Alice", role: "requester" },
  { id: 5, display_name: "Erin", role: "helper" },
  { id: 7, display_name: "Grace", role: "helper" },
];
const entry = {
  id: 27, requester_name: "Alice", category: "borrow", need_summary: "Casio 科学计算器",
  item_type: "scientific_calculator", location: "G", deadline: "2027-01-01T10:00:00Z",
  urgency: "high", status: "awaiting_response",
};
const viewer = { id: 5, display_name: "Erin" };
const offer = {
  id: 40, request_id: 27, helper_id: 5, category: "borrow", need_summary: entry.need_summary,
  item_type: null, item_name: null, response_type: "direct", help_note: "我会准时到 G 栋",
  offered_brand: "Casio", offered_model: "fx-991",
  location: "Z", deadline: entry.deadline, status: "accepted", request_status: "matched", sent_at: "2026-11-11T00:00:00Z",
  expires_at: entry.deadline, requester_confirmed: false, helper_confirmed: false,
};

function setupErin() {
  sessionStorage.setItem("demoActorId", "5");
  render(<MemoryRouter initialEntries={["/helper-board"]}><App /></MemoryRouter>);
}

test("every open request is actionable without exposing preset inventory or location", async () => {
  const response = { viewer, requests: [
    entry,
    { ...entry, id: 28, category: "service", need_summary: "搬运实验器材", item_type: "other", urgency: "normal",
      other_helper_location: "A", other_helper_reliability: "secret-score" },
  ], dismissed_requests: [], closed_requests: [], candidate_count: "secret-count" };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url === "/api/demo/roles" ? roles : url === "/api/helper-board" ? response : [] })));
  setupErin();
  expect(await screen.findByRole("heading", { name: "Erin 的求助广场" })).toBeInTheDocument();
  expect(await screen.findByRole("option", { name: "Grace · Helper" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "我的物品" })).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("当前位置");
  expect(within(screen.getByLabelText("求助 27")).getByRole("button", { name: "我可以帮助" })).toBeEnabled();
  expect(within(screen.getByLabelText("求助 28")).getByRole("button", { name: "我可以帮助" })).toBeEnabled();
  expect(screen.getByText("搬运实验器材")).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("secret-count");
  expect(document.body).not.toHaveTextContent("secret-score");
  expect(document.body).not.toHaveTextContent("other_helper_location");
});

test("dismiss hides a request only for the current Helper and restore brings it back", async () => {
  let board = { viewer, requests: [entry], dismissed_requests: [] as typeof entry[], closed_requests: [] };
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/dismiss")) board = { ...board, requests: [], dismissed_requests: [entry] };
    if (url.endsWith("/restore")) board = { ...board, requests: [entry], dismissed_requests: [] };
    return { ok: true, json: async () => url === "/api/demo/roles" ? roles : url === "/api/helper-board" ? board : [] };
  });
  vi.stubGlobal("fetch", fetchMock);
  setupErin();
  fireEvent.click(await screen.findByRole("button", { name: "暂不参与" }));
  expect(await screen.findByText("已隐藏的请求（1）")).toBeInTheDocument();
  expect(screen.queryByLabelText("求助 27")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("已隐藏的请求（1）"));
  fireEvent.click(screen.getByRole("button", { name: "恢复显示" }));
  expect(await screen.findByLabelText("求助 27")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/requests/27/dismiss", expect.objectContaining({
    method: "POST", headers: { "X-Demo-User-Id": "5" },
  }));
  expect(fetchMock).toHaveBeenCalledWith("/api/requests/27/restore", expect.objectContaining({
    method: "POST", headers: { "X-Demo-User-Id": "5" },
  }));
});

test("claim uses the Helper identity and keeps a single own accepted offer for handoff", async () => {
  let board = { viewer, requests: [entry], dismissed_requests: [], closed_requests: [] as Array<{ id: number; status: string }> };
  let ownOffers: typeof offer[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    if (url.endsWith("/claim")) {
      board = { ...board, requests: [], closed_requests: [{ id: 27, status: "matched" }] };
      ownOffers = [offer];
      return { ok: true, json: async () => offer };
    }
    return { ok: true, json: async () => url === "/api/demo/roles" ? roles : url === "/api/helper-board" ? board :
      url.includes("/helpers/") ? ownOffers : [] };
  });
  vi.stubGlobal("fetch", fetchMock);
  setupErin();
  fireEvent.click(await screen.findByRole("button", { name: "我可以帮助" }));
  expect(await screen.findByRole("dialog", { name: "确认响应" })).toHaveTextContent("Casio 科学计算器");
  fireEvent.click(screen.getByLabelText("我确认自己能够在截止时间前完成该请求"));
  fireEvent.change(screen.getByLabelText("帮助说明（可选）"), { target: { value: "我会准时到 G 栋" } });
  fireEvent.change(screen.getByLabelText("实际提供品牌（可选）"), { target: { value: "Casio" } });
  fireEvent.click(screen.getByRole("button", { name: "确认响应" }));
  expect(await screen.findByLabelText("我的认领 27")).toBeInTheDocument();
  expect(screen.getByText("当前没有开放请求。")).toBeInTheDocument();
  expect(screen.queryByText("该请求已被其他同学接下")).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith("/claim"))).toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledWith("/api/requests/27/claim", expect.objectContaining({
    method: "POST", headers: { "X-Demo-User-Id": "5", "Content-Type": "application/json" },
  }));
  const claim = fetchMock.mock.calls.find(([url]) => url.endsWith("/claim"));
  expect(JSON.parse((claim?.[1] as RequestInit).body as string)).toMatchObject({
    capability_confirmed: true, help_note: "我会准时到 G 栋", offered_brand: "Casio",
  });
});

test("a losing concurrent claim shows the safe 409 message and refreshes the board", async () => {
  let board = { viewer, requests: [entry], dismissed_requests: [], closed_requests: [] as Array<{ id: number; status: string }> };
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/claim")) {
      board = { ...board, requests: [], closed_requests: [{ id: 27, status: "matched" }] };
      return { ok: false, status: 409, json: async () => ({ detail: "该请求已被其他同学接下", code: "already_claimed" }) };
    }
    return { ok: true, json: async () => url === "/api/demo/roles" ? roles : url === "/api/helper-board" ? board : [] };
  });
  vi.stubGlobal("fetch", fetchMock);
  setupErin();
  fireEvent.click(await screen.findByRole("button", { name: "我可以帮助" }));
  fireEvent.click(screen.getByLabelText("我确认自己能够在截止时间前完成该请求"));
  fireEvent.click(screen.getByRole("button", { name: "确认响应" }));
  expect(await screen.findByText("该请求已被其他同学接下")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("当前没有开放请求。")).toBeInTheDocument());
  expect(screen.queryByLabelText("我的认领 27")).not.toBeInTheDocument();
});

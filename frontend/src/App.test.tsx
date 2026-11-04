import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

const saved = {
  id: 7,
  requester_id: 1,
  category: "borrow",
  raw_text: "要考试",
  item_type: "scientific_calculator",
  location: "VA",
  deadline: "2027-01-01T10:00:00Z",
  urgency: null,
  status: "draft",
  created_at: "2026-11-04T10:00:00Z",
  updated_at: "2026-11-04T10:00:00Z",
};

function mockFetch() {
  return vi.fn().mockResolvedValue({ ok: true, json: async () => saved });
}

function futureLocalDateTime() {
  const future = new Date(Date.now() + 60 * 60 * 1000);
  return new Date(future.getTime() - future.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

test("submits the form and opens the persisted request page", async () => {
  const fetchMock = mockFetch();
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("交接地点"), { target: { value: "VA" } });
  fireEvent.change(screen.getByLabelText("最晚需要时间"), { target: { value: futureLocalDateTime() } });
  fireEvent.click(screen.getByRole("button", { name: "保存请求" }));
  await screen.findByText(/状态：草稿/);
  expect(fetchMock).toHaveBeenCalledWith("/api/requests", expect.objectContaining({ method: "POST" }));
  expect(fetchMock).toHaveBeenCalledWith("/api/requests/7", undefined);
});

test("loads the request from the API when the detail route opens directly", async () => {
  const fetchMock = mockFetch();
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/requests/7"]}><App /></MemoryRouter>);
  expect(await screen.findByText(/状态：草稿/)).toBeInTheDocument();
  expect(screen.getByText("VA")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/requests/7", undefined);
});

test("shows API validation errors without navigating", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: "deadline must be in the future" }) }));
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("交接地点"), { target: { value: "VA" } });
  fireEvent.change(screen.getByLabelText("最晚需要时间"), { target: { value: futureLocalDateTime() } });
  fireEvent.click(screen.getByRole("button", { name: "保存请求" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("deadline must be in the future"));
  expect(screen.getByRole("heading", { name: "创建借物请求" })).toBeInTheDocument();
});

test("starts matching from a draft and renders public timeline events", async () => {
  const searching = {
    ...saved,
    status: "awaiting_response",
    events: [{ id: 1, event_type: "offer_sent", public_message: "已联系 Bob", created_at: saved.created_at }],
  };
  const fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    json: async () => url.endsWith("/search") ? searching : saved,
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/requests/7"]}><App /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "开始匹配" }));
  expect(await screen.findByText("已联系 Bob")).toBeInTheDocument();
  expect(screen.getByText(/状态：等待帮助者回复/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/requests/7/search", expect.objectContaining({ method: "POST" }));
});

test("switches to Bob and declines only his own offer", async () => {
  const offer = {
    id: 11, request_id: 7, helper_id: 2, item_type: "scientific_calculator",
    item_name: "Scientific calculator", location: "VA", deadline: saved.deadline,
    status: "pending", request_status: "awaiting_response", sent_at: saved.created_at,
    expires_at: saved.deadline, requester_confirmed: false, helper_confirmed: false,
  };
  let declined = false;
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/decline")) {
      declined = true;
      return { ok: true, json: async () => ({ ...offer, status: "declined" }) };
    }
    if (url.includes("/helpers/2/offers")) {
      return { ok: true, json: async () => [{ ...offer, status: declined ? "declined" : "pending" }] };
    }
    return { ok: true, json: async () => saved };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/requests/7"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("当前角色"), { target: { value: "2" } });
  fireEvent.click(await screen.findByRole("button", { name: "拒绝" }));
  await waitFor(() => expect(screen.getByText(/declined/)).toBeInTheDocument());
  expect(fetchMock).toHaveBeenCalledWith("/api/offers/11/decline", expect.objectContaining({
    method: "POST", headers: { "X-Demo-User-Id": "2" },
  }));
  expect(declined).toBe(true);
});

test("requester confirmation waits for helper confirmation", async () => {
  let current = { ...saved, status: "matched", matched_helper: "Carol", handoff_location: "VA", requester_confirmed: false };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/start")) current = { ...current, status: "in_progress" };
    if (url.endsWith("/complete")) current = { ...current, requester_confirmed: true };
    return { ok: true, json: async () => current };
  }));
  render(<MemoryRouter initialEntries={["/requests/7"]}><App /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "开始交接" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认完成" }));
  expect(await screen.findByText("你已确认，等待帮助者确认。")).toBeInTheDocument();
  expect(screen.getByText(/状态：交接中/)).toBeInTheDocument();
});

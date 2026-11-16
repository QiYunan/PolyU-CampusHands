import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  sessionStorage.clear();
});

const saved = {
  id: 7,
  requester_id: 1,
  category: "borrow",
  need_summary: "科学计算器",
  raw_text: "要考试",
  item_type: "scientific_calculator",
  preferred_brand: null,
  preferred_model: null,
  substitution_policy: "equivalent_ok",
  matching_issue: null,
  location: "VA",
  deadline: "2027-01-01T10:00:00Z",
  urgency: "normal",
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

test("hides the structured debug form by default", async () => {
  vi.stubGlobal("fetch", mockFetch());
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  expect(screen.queryByRole("heading", { name: /结构化表单/ })).not.toBeInTheDocument();
  expect(screen.getByLabelText("描述你的需求")).toBeInTheDocument();
});

test("the explicit development switch restores the structured debug form", async () => {
  vi.stubEnv("VITE_SHOW_STRUCTURED_DEBUG_FORM", "true");
  const fetchMock = mockFetch();
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: /结构化表单/ })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("需求摘要", { selector: "input#need-summary" }), { target: { value: "科学计算器" } });
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
  vi.stubEnv("VITE_SHOW_STRUCTURED_DEBUG_FORM", "true");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: "deadline must be in the future" }) }));
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("需求摘要", { selector: "input#need-summary" }), { target: { value: "科学计算器" } });
  fireEvent.change(screen.getByLabelText("交接地点"), { target: { value: "VA" } });
  fireEvent.change(screen.getByLabelText("最晚需要时间"), { target: { value: futureLocalDateTime() } });
  fireEvent.click(screen.getByRole("button", { name: "保存请求" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("deadline must be in the future"));
  expect(screen.getByRole("heading", { name: "描述你的需求" })).toBeInTheDocument();
});

test("publishes a draft and renders a public publication event", async () => {
  const published = {
    ...saved,
    status: "awaiting_response",
    events: [{ id: 1, event_type: "request_published", public_message: "请求已发布到求助广场", created_at: saved.created_at }],
  };
  const fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    json: async () => url.endsWith("/publish") ? published : saved,
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/requests/7"]}><App /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "发布到求助广场" }));
  expect(await screen.findByText("请求已发布到求助广场")).toBeInTheDocument();
  expect(screen.getByText(/状态：已发布，等待帮助者认领/)).toBeInTheDocument();
  expect(screen.getByText("请求已发布，正在等待校园内的帮助者响应。")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/requests/7/publish", expect.objectContaining({ method: "POST" }));
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

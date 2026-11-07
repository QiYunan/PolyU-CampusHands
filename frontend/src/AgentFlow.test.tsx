import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

const draft = {
  id: 5, raw_text: "我想借一部科学计算器", item_type: "scientific_calculator", location: null,
  deadline: null, urgency: null, missing_fields: ["location", "deadline"],
  public_question: "请补充交接地点和最晚需要时间。", status: "collecting_details",
  request_id: null, provider: "mock", fallback_active: false,
};
const ready = { ...draft, location: "VA", deadline: "2027-01-01T10:00:00Z", missing_fields: [], public_question: null, status: "ready" };
const request = {
  id: 8, requester_id: 1, category: "borrow", raw_text: draft.raw_text,
  item_type: "scientific_calculator", location: "VA", deadline: ready.deadline,
  urgency: "high", status: "draft", created_at: "2026-11-05T00:00:00Z", updated_at: "2026-11-05T00:00:00Z",
  events: [{ id: 1, event_type: "request_parsed", public_message: "已解析并确认借物请求", created_at: "2026-11-05T00:00:00Z" }],
};

test("clarifies, edits, confirms and starts Agent matching", async () => {
  let current = request;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    let value: unknown;
    if (url === "/api/system/llm-status") value = { primary: "mock", primary_status: "available", fallback: null, fallback_status: null, fallback_active: false };
    else if (url === "/api/agent/drafts" && init?.method === "POST") value = draft;
    else if (url.endsWith("/clarify")) value = ready;
    else if (url === "/api/agent/drafts/5" && init?.method === "PATCH") value = { ...ready, location: "PQ" };
    else if (url.endsWith("/confirm")) value = current;
    else if (url.endsWith("/search")) { current = { ...request, status: "awaiting_response" }; value = { request_id: 8, status: "awaiting_response", step_count: 2, provider: "mock", fallback_active: false, message: "等待帮助者回复", action_committed: true, validated_actions: ["send_help_offer"] }; }
    else if (url.endsWith("/observe")) value = { request_id: 8, status: "awaiting_response", step_count: 1, provider: "mock", fallback_active: false, message: "已联系 Carol", action_committed: false };
    else value = current;
    return { ok: true, json: async () => value };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("借物请求"), { target: { value: draft.raw_text } });
  fireEvent.click(screen.getByRole("button", { name: "解析需求" }));
  expect(await screen.findByText(draft.public_question)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("补充缺失信息"), { target: { value: "在VA，20分钟后" } });
  fireEvent.click(screen.getByRole("button", { name: "提交补充" }));
  expect(await screen.findByText(/等待你确认/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("交接地点", { selector: "input#parsed-location" }), { target: { value: "PQ" } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  await waitFor(() => expect(screen.getByLabelText("交接地点", { selector: "input#parsed-location" })).toHaveValue("PQ"));
  fireEvent.click(screen.getByRole("button", { name: "确认并保存草稿" }));
  fireEvent.click(await screen.findByRole("button", { name: "Agent 开始匹配" }));
  expect(await screen.findByText(/状态：等待帮助者回复/)).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 操作结果")).toHaveTextContent("send_help_offer");
  expect(screen.getByLabelText("Agent 操作结果")).toHaveTextContent("Mock Recovery Mode");
  expect(screen.getByLabelText("Agent 操作结果")).toHaveTextContent("服务已提交操作");
  fireEvent.click(screen.getByRole("button", { name: "Agent 查看下一步" }));
  expect(await screen.findByText(/当时结果：已联系 Carol/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/agent/requests/8/search", expect.objectContaining({ method: "POST" }));
});

test("provider error leaves the natural form usable", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/system/llm-status" ?
    { ok: true, json: async () => ({ primary: "deepseek", primary_status: "unavailable", fallback: "ollama", fallback_status: "unavailable", fallback_active: false }) } :
    { ok: false, status: 503, json: async () => ({ detail: "模型暂不可用，请稍后重试。" }) }));
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("借物请求"), { target: { value: "我想借计算器" } });
  fireEvent.click(screen.getByRole("button", { name: "解析需求" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("模型暂不可用");
  expect(screen.getByRole("button", { name: "解析需求" })).toBeEnabled();
  expect(screen.getByRole("heading", { name: /结构化表单/ })).toBeInTheDocument();
});

test("rapid repeated natural-language submits create only one draft", async () => {
  let resolveDraft: ((value: { ok: boolean; json: () => Promise<typeof draft> }) => void) | undefined;
  const fetchMock = vi.fn((url: string) => {
    if (url === "/api/system/llm-status") return Promise.resolve({ ok: true, json: async () => ({ primary: "mock", fallback: "mock", active: null, primary_status: "unknown", fallback_status: "unknown", fallback_active: false }) });
    return new Promise<{ ok: boolean; json: () => Promise<typeof draft> }>((resolve) => { resolveDraft = resolve; });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("借物请求"), { target: { value: draft.raw_text } });
  const parse = screen.getByRole("button", { name: "解析需求" });
  fireEvent.click(parse);
  fireEvent.click(parse);
  expect(fetchMock.mock.calls.filter(([url]) => url === "/api/agent/drafts")).toHaveLength(1);
  expect(screen.getByRole("button", { name: "正在解析需求…" })).toBeDisabled();
  resolveDraft?.({ ok: true, json: async () => draft });
  expect(await screen.findByText(draft.public_question)).toBeInTheDocument();
});

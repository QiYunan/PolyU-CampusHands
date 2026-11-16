import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

const draft = {
  id: 5, raw_text: "我想借一部科学计算器", category: "borrow", need_summary: "科学计算器", item_type: "scientific_calculator", location: null,
  deadline: null, urgency: null, missing_fields: ["location", "deadline"],
  preferred_brand: null, preferred_model: null, substitution_policy: "equivalent_ok", matching_issue: null,
  public_question: "请补充交接地点和最晚需要时间。", status: "collecting_details",
  request_id: null, provider: "mock", fallback_active: false,
};
const ready = { ...draft, location: "VA", deadline: "2027-01-01T10:00:00Z", missing_fields: [], public_question: null, status: "ready" };
const request = {
  id: 8, requester_id: 1, category: "borrow", raw_text: draft.raw_text,
  need_summary: "Casio fx-991cnx 科学计算器", item_type: "scientific_calculator", preferred_brand: "Casio", preferred_model: "fx-991cnx",
  substitution_policy: "exact_only", matching_issue: null, location: "PQ", deadline: ready.deadline,
  urgency: "high", status: "draft", created_at: "2026-11-05T00:00:00Z", updated_at: "2026-11-05T00:00:00Z",
  events: [{ id: 1, event_type: "request_parsed", public_message: "已解析并确认借物请求", created_at: "2026-11-05T00:00:00Z" }],
};

test("atomically confirms current edits and publishes through the controlled Agent action", async () => {
  let current = request;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    let value: unknown;
    if (url === "/api/system/llm-status") value = { primary: "mock", primary_status: "available", fallback: null, fallback_status: null, fallback_active: false };
    else if (url === "/api/agent/drafts" && init?.method === "POST") value = draft;
    else if (url.endsWith("/clarify")) value = ready;
    else if (url.endsWith("/confirm")) value = current;
    else if (url.endsWith("/search")) { current = { ...request, status: "awaiting_response" }; value = { request_id: 8, status: "awaiting_response", step_count: 2, provider: "mock", fallback_active: false, message: "请求已发布", action_committed: true, validated_actions: ["publish_request"] }; }
    else if (url.endsWith("/observe")) value = { request_id: 8, status: "awaiting_response", step_count: 1, provider: "mock", fallback_active: false, message: "请求仍在广场开放", action_committed: false };
    else value = current;
    return { ok: true, json: async () => value };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("描述你的需求"), { target: { value: draft.raw_text } });
  fireEvent.click(screen.getByRole("button", { name: "解析需求" }));
  expect(await screen.findByText(draft.public_question)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("补充缺失信息"), { target: { value: "在VA，20分钟后" } });
  fireEvent.click(screen.getByRole("button", { name: "提交补充" }));
  expect(await screen.findByText(/等待你确认/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("交接地点", { selector: "input#parsed-location" }), { target: { value: "PQ" } });
  fireEvent.change(screen.getByLabelText("需求摘要", { selector: "input#parsed-summary" }), { target: { value: "Casio fx-991cnx 科学计算器" } });
  fireEvent.change(screen.getByLabelText("优先品牌（可选）", { selector: "input#parsed-brand" }), { target: { value: "Casio" } });
  fireEvent.change(screen.getByLabelText("优先型号（可选）", { selector: "input#parsed-model" }), { target: { value: "fx-991cnx" } });
  fireEvent.change(screen.getByLabelText("替代品规则", { selector: "select#parsed-substitution-policy" }), { target: { value: "exact_only" } });
  fireEvent.change(screen.getByLabelText("紧急程度", { selector: "select#parsed-urgency" }), { target: { value: "high" } });
  fireEvent.click(screen.getByRole("button", { name: "确认并创建请求" }));
  const confirm = fetchMock.mock.calls.find(([url]) => url.endsWith("/confirm"));
  expect(confirm).toBeDefined();
  expect(JSON.parse((confirm?.[1] as RequestInit).body as string)).toMatchObject({
    category: "borrow", need_summary: "Casio fx-991cnx 科学计算器", location: "PQ", urgency: "high",
    preferred_brand: "Casio", preferred_model: "fx-991cnx", substitution_policy: "exact_only",
  });
  expect(fetchMock.mock.calls.some(([url, init]) => url === "/api/agent/drafts/5" && init?.method === "PATCH")).toBe(false);
  fireEvent.click(await screen.findByRole("button", { name: "Agent 发布请求" }));
  expect(await screen.findByText(/状态：已发布，等待帮助者认领/)).toBeInTheDocument();
  expect(screen.getByLabelText("Agent 操作结果")).toHaveTextContent("publish_request");
  expect(screen.getByLabelText("Agent 操作结果")).toHaveTextContent("Mock Recovery Mode");
  expect(screen.getByLabelText("Agent 操作结果")).toHaveTextContent("服务已提交操作");
  fireEvent.click(screen.getByRole("button", { name: "Agent 查看下一步" }));
  expect(await screen.findByText(/当时结果：请求仍在广场开放/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/agent/requests/8/search", expect.objectContaining({ method: "POST" }));
});

test("provider error leaves the natural form usable", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/system/llm-status" ?
    { ok: true, json: async () => ({ primary: "deepseek", primary_status: "unavailable", fallback: "ollama", fallback_status: "unavailable", fallback_active: false }) } :
    { ok: false, status: 503, json: async () => ({ detail: "模型暂不可用，请稍后重试。" }) }));
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("描述你的需求"), { target: { value: "我想借计算器" } });
  fireEvent.click(screen.getByRole("button", { name: "解析需求" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("模型暂不可用");
  expect(screen.getByRole("button", { name: "解析需求" })).toBeEnabled();
  expect(screen.queryByRole("heading", { name: /结构化表单/ })).not.toBeInTheDocument();
});

test("service drafts hide item preferences and confirm with the other fallback", async () => {
  const serviceDraft = {
    ...ready, id: 6, raw_text: "20分钟后在Z栋帮我搬实验器材", category: "service", need_summary: "有偿帮忙搬运实验器材",
    item_type: "other", preferred_brand: null, preferred_model: null, substitution_policy: "equivalent_ok",
  };
  const serviceRequest = {
    ...request, id: 9, category: "service", need_summary: serviceDraft.need_summary, raw_text: serviceDraft.raw_text,
    item_type: "other", preferred_brand: null, preferred_model: null, substitution_policy: "equivalent_ok",
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    return {
      ok: true,
      json: async () => url === "/api/system/llm-status" ?
        { primary: "mock", primary_status: "available", fallback: null, fallback_status: null, fallback_active: false } :
        url.endsWith("/confirm") ? serviceRequest : serviceDraft,
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("描述你的需求"), { target: { value: serviceDraft.raw_text } });
  fireEvent.click(screen.getByRole("button", { name: "解析需求" }));
  expect(await screen.findByText(/需求类型：寻求服务/)).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByLabelText("物品", { selector: "select#parsed-item" })).not.toBeInTheDocument());
  expect(screen.queryByLabelText("优先品牌（可选）", { selector: "input#parsed-brand" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "确认并创建请求" }));
  const confirm = fetchMock.mock.calls.find(([url]) => url.endsWith("/confirm"));
  expect(JSON.parse((confirm?.[1] as RequestInit).body as string)).toMatchObject({
    category: "service", need_summary: "有偿帮忙搬运实验器材", item_type: "other",
    preferred_brand: null, preferred_model: null, substitution_policy: "equivalent_ok",
  });
});

test("rapid repeated natural-language submits create only one draft", async () => {
  let resolveDraft: ((value: { ok: boolean; json: () => Promise<typeof draft> }) => void) | undefined;
  const fetchMock = vi.fn((url: string) => {
    if (url === "/api/system/llm-status") return Promise.resolve({ ok: true, json: async () => ({ primary: "mock", fallback: "mock", active: null, primary_status: "unknown", fallback_status: "unknown", fallback_active: false }) });
    return new Promise<{ ok: boolean; json: () => Promise<typeof draft> }>((resolve) => { resolveDraft = resolve; });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("描述你的需求"), { target: { value: draft.raw_text } });
  const parse = screen.getByRole("button", { name: "解析需求" });
  fireEvent.click(parse);
  fireEvent.click(parse);
  expect(fetchMock.mock.calls.filter(([url]) => url === "/api/agent/drafts")).toHaveLength(1);
  expect(screen.getByRole("button", { name: "正在解析需求…" })).toBeDisabled();
  resolveDraft?.({ ok: true, json: async () => draft });
  expect(await screen.findByText(draft.public_question)).toBeInTheDocument();
});

import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

const proposal = {
  id: 61, helper_name: "Erin", help_note: "我可以带一台功能相同的计算器",
  offered_brand: "Canon", offered_model: "F-789", status: "proposed",
};

const request = {
  id: 27, requester_id: 1, category: "borrow", need_summary: "Casio fx-991cnx 科学计算器",
  raw_text: "30分钟之后，在Z栋交接，需要一台Casio计算器", item_type: "scientific_calculator",
  preferred_brand: "Casio", preferred_model: "fx-991cnx", substitution_policy: "ask_before_substitute",
  matching_issue: null, location: "Z", deadline: "2027-01-01T10:00:00Z", urgency: "high",
  status: "awaiting_response", created_at: "2026-11-10T00:00:00Z", updated_at: "2026-11-10T00:00:00Z",
  events: [], proposals: [proposal],
};

test("requester accepts a concrete substitute proposal before the request becomes matched", async () => {
  let current = request;
  const matched = {
    ...request, status: "matched", proposals: [], matched_helper: "Erin", helper_note: proposal.help_note,
    offered_brand: proposal.offered_brand, offered_model: proposal.offered_model, response_type: "substitute",
  };
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/accept-proposal")) current = matched;
    return { ok: true, json: async () => current };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/requests/27"]}><App /></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Erin 提出的替代方案" })).toBeInTheDocument();
  expect(screen.getByText(/Canon F-789/)).toBeInTheDocument();
  expect(screen.getByText(/功能相同/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "接受替代方案" }));

  expect(await screen.findByText(/状态：匹配成功/)).toBeInTheDocument();
  expect(screen.getByText("Erin")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Erin 提出的替代方案" })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/offers/61/accept-proposal", expect.objectContaining({ method: "POST" }));
});

test("requester can decline a proposal while the open request remains available", async () => {
  let current = request;
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/decline-proposal")) current = { ...request, proposals: [] };
    return { ok: true, json: async () => current };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/requests/27"]}><App /></MemoryRouter>);

  fireEvent.click(await screen.findByRole("button", { name: "拒绝替代方案" }));
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Erin 提出的替代方案" })).not.toBeInTheDocument());
  expect(screen.getByText(/状态：已发布，等待帮助者认领/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/offers/61/decline-proposal", expect.objectContaining({ method: "POST" }));
});

test("service request details use the summary and hide borrowing preferences", async () => {
  const service = {
    ...request, id: 28, category: "service", need_summary: "有偿帮忙搬运实验器材", item_type: "other",
    preferred_brand: null, preferred_model: null, substitution_policy: "equivalent_ok", proposals: [],
  };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => service })));
  render(<MemoryRouter initialEntries={["/requests/28"]}><App /></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "有偿帮忙搬运实验器材" })).toBeInTheDocument();
  expect(screen.getByText("寻求服务")).toBeInTheDocument();
  expect(screen.getByText("紧急")).toBeInTheDocument();
  expect(screen.queryByText("优先品牌")).not.toBeInTheDocument();
  expect(screen.queryByText("替代品规则")).not.toBeInTheDocument();
});

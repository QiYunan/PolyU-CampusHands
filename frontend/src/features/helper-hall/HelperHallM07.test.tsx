import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { InvitationInboxPanel } from "./InvitationInboxPanel";
import { TodayStatusPanel } from "./TodayStatusPanel";
import type { InvitationInbox } from "./types";


afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const profile = {
  user_id: 5,
  items: [{ id: 21, item_type: "scientific_calculator", item_name: "Casio fx-991CN X", brand: "Casio", model: "fx-991CN X", active: true, available: true }],
  services: [{ id: 8, service_code: "moving", service_name: "搬运实验器材", active: true }],
};

const daily = {
  local_date: "2026-11-16",
  availability: null,
  suggested_item_ids: [21, 999],
  suggested_service_ids: [8, 999],
};

const locations = [{ code: "Z", label_zh: "Z座", label_en: "Block Z" }];

test("today status reuses prior capability choices without re-entering inventory", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/locations") return { ok: true, json: async () => locations };
    if (url.endsWith("/helper-profile")) return { ok: true, json: async () => profile };
    if (url.endsWith("/daily-availability") && init?.method === "PUT") {
      return { ok: true, json: async () => ({ ...daily, availability: JSON.parse(init.body as string) }) };
    }
    if (url.endsWith("/daily-availability")) return { ok: true, json: async () => daily };
    throw new Error(`Unexpected URL ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<TodayStatusPanel actorId={5} />);

  expect(await screen.findByRole("heading", { name: "我的今日状态" })).toBeInTheDocument();
  expect(screen.getByDisplayValue("Casio fx-991CN X")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "沿用上次清单" }));
  expect(within(screen.getByRole("group", { name: "今天愿意提供的物品" })).getByRole("checkbox")).toBeChecked();
  expect(within(screen.getByRole("group", { name: "今天愿意提供的服务" })).getByRole("checkbox")).toBeChecked();
  fireEvent.click(screen.getByLabelText("今天愿意提供帮助"));
  fireEvent.click(screen.getByRole("button", { name: "保存今日状态" }));
  expect(await screen.findByText("今日状态已更新，将在今天结束后自动失效。")).toBeInTheDocument();
  const update = fetchMock.mock.calls.find(([url, init]) => url.endsWith("/daily-availability") && init?.method === "PUT");
  expect(JSON.parse((update?.[1] as RequestInit).body as string)).toMatchObject({
    willing: true,
    item_ids: [21],
    service_ids: [8],
  });
});

test("invitation inbox exposes targeted actions and no public board", async () => {
  const inboxProfile = {
    ...profile,
    items: [
      ...profile.items,
      { id: 22, item_type: "scientific_calculator", item_name: "Not selected today", brand: null, model: null, active: true, available: true },
      { id: 23, item_type: "scientific_calculator", item_name: "Already lent out", brand: null, model: null, active: true, available: false },
    ],
  };
  const inboxDaily = {
    ...daily,
    suggested_item_ids: [],
    suggested_service_ids: [],
    availability: {
      willing: true,
      available_from: "2026-11-16T13:00:00+08:00",
      available_until: "2026-11-16T18:00:00+08:00",
      campus_building: "Z",
      accepts_urgent: true,
      item_ids: [21, 23],
      service_ids: [8],
    },
  };
  let inbox: InvitationInbox = {
    helper_id: 5,
    pending: [{
      id: 31, batch_id: 9, round_number: 1, request_id: 42, helper_id: 5, helper_name: "Erin", requester_name: "Alice",
      category: "borrow", request_item_type: "scientific_calculator", need_summary: "Casio fx-991CN X 科学计算器", location: "Z",
      deadline: "2026-11-16T14:00:00Z", urgency: "high", match_reason: "exact_model",
      response_type: "direct", status: "pending", decline_reason: null, note: null,
      item_id: 21, item_name: "Casio fx-991CN X", service_id: null, service_name: null,
      request_status: "awaiting_response", sent_at: "2026-11-16T13:00:00Z",
      responded_at: null, expires_at: "2026-11-16T14:00:00Z", offer_id: null, helper_confirmed: false,
    }],
    active: [],
    history: [],
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/helper-profile")) return { ok: true, json: async () => inboxProfile };
    if (url.endsWith("/daily-availability")) return { ok: true, json: async () => inboxDaily };
    if (url.endsWith("/accept") && init?.method === "POST") {
      const accepted = { ...inbox.pending[0], status: "accepted", request_status: "matched", offer_id: 51 };
      inbox = { ...inbox, pending: [], active: [accepted] };
      return { ok: true, json: async () => ({ id: 51, status: "accepted" }) };
    }
    if (url.endsWith("/invitations")) return { ok: true, json: async () => inbox };
    throw new Error(`Unexpected URL ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<InvitationInboxPanel actorId={5} />);

  expect(await screen.findByRole("heading", { name: "收到的邀请" })).toBeInTheDocument();
  expect(screen.getByText("这里只出现系统定向发送给你的请求，不需要浏览公开求助帖。")).toBeInTheDocument();
  expect(screen.queryByText("开放请求")).not.toBeInTheDocument();
  const substituteSelect = screen.getByLabelText("替代物品 31");
  expect(within(substituteSelect).getByRole("option", { name: "Casio fx-991CN X" })).toBeInTheDocument();
  expect(within(substituteSelect).queryByRole("option", { name: "Not selected today" })).not.toBeInTheDocument();
  expect(within(substituteSelect).queryByRole("option", { name: "Already lent out" })).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "接受" }));
  expect(await screen.findByText("已接受邀请。")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("当前没有待处理邀请。")).toBeInTheDocument());
  expect(screen.getByLabelText("进行中任务 31")).toBeInTheDocument();
});

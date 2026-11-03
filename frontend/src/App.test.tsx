import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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

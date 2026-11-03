export const itemTypes = {
  scientific_calculator: "科学计算器",
  charger: "充电器",
  adapter: "转接头",
  stationery: "文具",
  umbrella: "雨伞",
} as const;

export type ItemType = keyof typeof itemTypes;

export type HelpRequest = {
  id: number;
  requester_id: number;
  category: "borrow";
  raw_text: string | null;
  item_type: ItemType;
  location: string;
  deadline: string;
  urgency: string | null;
  status: "draft";
  created_at: string;
  updated_at: string;
};

export type RequestInput = {
  item_type: ItemType;
  location: string;
  deadline: string;
  raw_text?: string;
};

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new Error("无法连接后端，请确认服务已启动。");
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    let message = `请求失败（${response.status}）`;
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = body.detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) {
        message = detail
          .map((entry: { msg?: string }) => entry.msg ?? "输入有误")
          .join("；");
      }
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function createHelpRequest(input: RequestInput): Promise<HelpRequest> {
  return api<HelpRequest>("/api/requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function getHelpRequest(id: string): Promise<HelpRequest> {
  return api<HelpRequest>(`/api/requests/${encodeURIComponent(id)}`);
}

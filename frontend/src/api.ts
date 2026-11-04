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
  status: "draft" | "collecting_details" | "searching" | "awaiting_response" | "matched" | "in_progress" | "completed" | "cancelled" | "expired" | "failed";
  created_at: string;
  updated_at: string;
  events?: PublicEvent[];
  matched_helper?: string | null;
  handoff_location?: string | null;
  requester_confirmed?: boolean;
  helper_confirmed?: boolean;
};

export type PublicEvent = {
  id: number;
  event_type: string;
  public_message: string;
  created_at: string;
};

export type HelpOffer = {
  id: number;
  request_id: number;
  helper_id: number;
  item_type: ItemType;
  item_name: string;
  location: string;
  deadline: string;
  status: string;
  request_status: HelpRequest["status"];
  sent_at: string;
  expires_at: string;
  requester_confirmed: boolean;
  helper_confirmed: boolean;
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

export type RequestAction = "search" | "cancel" | "start" | "complete";

export function actOnRequest(id: string, action: RequestAction): Promise<HelpRequest> {
  return api<HelpRequest>(`/api/requests/${encodeURIComponent(id)}/${action}`, { method: "POST" });
}

function helperHeaders(helperId: number): HeadersInit {
  return { "X-Demo-User-Id": String(helperId) };
}

export function getHelperOffers(helperId: number): Promise<HelpOffer[]> {
  return api<HelpOffer[]>(`/api/helpers/${helperId}/offers`, { headers: helperHeaders(helperId) });
}

export type OfferAction = "accept" | "decline" | "confirm-completion";

export function actOnOffer(offerId: number, helperId: number, action: OfferAction): Promise<HelpOffer> {
  return api<HelpOffer>(`/api/offers/${offerId}/${action}`, { method: "POST", headers: helperHeaders(helperId) });
}

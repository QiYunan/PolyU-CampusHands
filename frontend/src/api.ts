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
  status: "draft" | "searching" | "awaiting_response" | "matched" | "in_progress" | "completed" | "cancelled" | "expired" | "failed";
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
  message?: string | null;
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

export type AgentDraft = {
  id: number;
  raw_text: string;
  item_type: ItemType | null;
  location: string | null;
  deadline: string | null;
  urgency: "normal" | "high" | null;
  missing_fields: Array<"item_type" | "location" | "deadline">;
  public_question: string | null;
  status: "collecting_details" | "ready" | "confirmed";
  request_id: number | null;
  provider: string | null;
  fallback_active: boolean;
};

export type LLMStatus = {
  primary: string;
  fallback: string | null;
  active: string | null;
  primary_status: string;
  fallback_status: string | null;
  fallback_active: boolean;
};

export type AgentRun = {
  request_id: number;
  status: HelpRequest["status"];
  step_count: number;
  provider: string | null;
  fallback_active: boolean;
  message: string;
  action_committed: boolean;
  validated_actions: Array<"search_helpers" | "send_help_offer">;
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

export function createAgentDraft(raw_text: string): Promise<AgentDraft> {
  return api("/api/agent/drafts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ raw_text }) });
}

export function getAgentDraft(id: number): Promise<AgentDraft> {
  return api(`/api/agent/drafts/${id}`);
}

export function clarifyAgentDraft(id: number, text: string): Promise<AgentDraft> {
  return api(`/api/agent/drafts/${id}/clarify`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
}

export function editAgentDraft(id: number, edits: Partial<Pick<AgentDraft, "item_type" | "location" | "deadline" | "urgency">>): Promise<AgentDraft> {
  return api(`/api/agent/drafts/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edits) });
}

export function confirmAgentDraft(id: number): Promise<HelpRequest> {
  return api(`/api/agent/drafts/${id}/confirm`, { method: "POST" });
}

export function agentSearch(id: string): Promise<AgentRun> {
  return api(`/api/agent/requests/${encodeURIComponent(id)}/search`, { method: "POST" });
}


export function agentObserve(id: string): Promise<AgentRun> {
  return api(`/api/agent/requests/${encodeURIComponent(id)}/observe`, { method: "POST" });
}

export function getLLMStatus(): Promise<LLMStatus> {
  return api("/api/system/llm-status");
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

export const itemTypes = {
  scientific_calculator: "科学计算器",
  charger: "充电器",
  adapter: "转接头",
  stationery: "文具",
  umbrella: "雨伞",
  other: "其他",
} as const;

export type ItemType = keyof typeof itemTypes;
export type RequestCategory = "borrow" | "service";
export type Urgency = "normal" | "high";

export type SubstitutionPolicy = "ask_before_substitute" | "exact_only" | "equivalent_ok";
export type MatchingIssue =
  | "unknown_location"
  | "no_item_inventory"
  | "exact_preference_unavailable"
  | "alternatives_available_needs_confirmation"
  | "no_available_helper"
  | "unreachable_before_deadline"
  | "candidate_exhausted";

export type CampusLocation = { code: string; label_zh: string; label_en: string };
export type DemoRole = { id: number; display_name: string; role: "requester" | "helper" };
export type BoardEntry = {
  id: number;
  requester_name: string;
  category: RequestCategory;
  need_summary: string;
  item_type: ItemType;
  location: string;
  deadline: string;
  urgency: Urgency;
  status: HelpRequest["status"];
};
export type HelperBoard = {
  viewer: {
    id: number;
    display_name: string;
  };
  requests: BoardEntry[];
  dismissed_requests: BoardEntry[];
  closed_requests: Array<{ id: number; status: HelpRequest["status"] }>;
};

export const substitutionPolicyLabels: Record<SubstitutionPolicy, string> = {
  ask_before_substitute: "替代品先征求同意",
  exact_only: "只接受准确品牌或型号",
  equivalent_ok: "接受同类兼容物品",
};

export type HelpRequest = {
  id: number;
  requester_id: number;
  category: RequestCategory;
  need_summary: string;
  raw_text: string | null;
  item_type: ItemType;
  preferred_brand: string | null;
  preferred_model: string | null;
  substitution_policy: SubstitutionPolicy;
  matching_issue: MatchingIssue | null;
  location: string;
  deadline: string;
  urgency: Urgency;
  status: "draft" | "searching" | "awaiting_response" | "matched" | "in_progress" | "completed" | "cancelled" | "expired" | "failed";
  created_at: string;
  updated_at: string;
  events?: PublicEvent[];
  matched_helper?: string | null;
  handoff_location?: string | null;
  requester_confirmed?: boolean;
  helper_confirmed?: boolean;
  helper_note?: string | null;
  offered_brand?: string | null;
  offered_model?: string | null;
  response_type?: "direct" | "substitute" | null;
  proposals?: RequestProposal[];
};

export type RequestProposal = {
  id: number;
  helper_name: string;
  help_note: string | null;
  offered_brand: string | null;
  offered_model: string | null;
  status: "proposed" | "declined" | "accepted" | string;
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
  category: RequestCategory;
  need_summary: string;
  item_type: ItemType | null;
  item_name: string | null;
  response_type: "direct" | "substitute";
  message?: string | null;
  help_note: string | null;
  offered_brand: string | null;
  offered_model: string | null;
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
  category: RequestCategory;
  need_summary: string;
  item_type: ItemType;
  location: string;
  deadline: string;
  urgency: Urgency;
  raw_text?: string;
  preferred_brand?: string | null;
  preferred_model?: string | null;
  substitution_policy?: SubstitutionPolicy;
};

export type RequestEdit = { location?: string; deadline?: string };

export type AgentDraft = {
  id: number;
  raw_text: string;
  category: RequestCategory;
  need_summary: string | null;
  item_type: ItemType | null;
  preferred_brand: string | null;
  preferred_model: string | null;
  substitution_policy: SubstitutionPolicy;
  matching_issue: MatchingIssue | null;
  location: string | null;
  deadline: string | null;
  urgency: Urgency | null;
  missing_fields: Array<"need_summary" | "location" | "deadline">;
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
  validated_actions: Array<"search_helpers" | "publish_request">;
  matching_issue: MatchingIssue | null;
};

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code: string | null) {
    super(message);
    this.name = "ApiError";
  }
}

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
    let code: string | null = null;
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = body.detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) {
        message = detail
          .map((entry: { msg?: string }) => entry.msg ?? "输入有误")
          .join("；");
      }
    }
    if (typeof body === "object" && body !== null && "code" in body && typeof body.code === "string") code = body.code;
    throw new ApiError(message, response.status, code);
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

export function editAgentDraft(id: number, edits: Partial<Pick<AgentDraft, "item_type" | "location" | "deadline" | "urgency" | "preferred_brand" | "preferred_model" | "substitution_policy">>): Promise<AgentDraft> {
  return api(`/api/agent/drafts/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edits) });
}

export type AgentDraftConfirmInput = Pick<AgentDraft,
  "category" | "need_summary" | "item_type" | "location" | "deadline" | "urgency" |
  "preferred_brand" | "preferred_model" | "substitution_policy"
>;

export function confirmAgentDraft(id: number, input: AgentDraftConfirmInput): Promise<HelpRequest> {
  return api(`/api/agent/drafts/${id}/confirm`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
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

export function getLocations(): Promise<CampusLocation[]> {
  return api<CampusLocation[]>("/api/locations");
}

export function getDemoRoles(): Promise<DemoRole[]> {
  return api<DemoRole[]>("/api/demo/roles");
}

export function editHelpRequest(id: string, edits: RequestEdit): Promise<HelpRequest> {
  return api<HelpRequest>(`/api/requests/${encodeURIComponent(id)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edits),
  });
}

export function acceptProposal(id: number): Promise<HelpRequest> {
  return api<HelpRequest>(`/api/offers/${id}/accept-proposal`, { method: "POST" });
}

export function declineProposal(id: number): Promise<HelpRequest> {
  return api<HelpRequest>(`/api/offers/${id}/decline-proposal`, { method: "POST" });
}

export type RequestAction = "publish" | "cancel" | "start" | "complete";

export function actOnRequest(id: string, action: RequestAction): Promise<HelpRequest> {
  return api<HelpRequest>(`/api/requests/${encodeURIComponent(id)}/${action}`, { method: "POST" });
}

function helperHeaders(helperId: number): HeadersInit {
  return { "X-Demo-User-Id": String(helperId) };
}

export function getHelperBoard(helperId: number): Promise<HelperBoard> {
  return api<HelperBoard>("/api/helper-board", { headers: helperHeaders(helperId) });
}

export function actOnBoardRequest(requestId: number, helperId: number, action: "dismiss" | "restore"): Promise<unknown> {
  return api(`/api/requests/${requestId}/${action}`, { method: "POST", headers: helperHeaders(helperId) });
}

export type ClaimInput = {
  capability_confirmed: true;
  response_type: "direct" | "substitute";
  help_note?: string | null;
  offered_brand?: string | null;
  offered_model?: string | null;
};

export function claimBoardRequest(requestId: number, helperId: number, input: ClaimInput): Promise<HelpOffer> {
  return api<HelpOffer>(`/api/requests/${requestId}/claim`, {
    method: "POST",
    headers: { ...helperHeaders(helperId), "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function getHelperOffers(helperId: number): Promise<HelpOffer[]> {
  return api<HelpOffer[]>(`/api/helpers/${helperId}/offers`, { headers: helperHeaders(helperId) });
}

export type OfferAction = "accept" | "decline" | "confirm-completion";

export function actOnOffer(offerId: number, helperId: number, action: OfferAction): Promise<HelpOffer> {
  return api<HelpOffer>(`/api/offers/${offerId}/${action}`, { method: "POST", headers: helperHeaders(helperId) });
}

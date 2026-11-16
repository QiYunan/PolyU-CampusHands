import type {
  CampusLocation,
  DailyAvailability,
  DailyAvailabilityData,
  HelperProfile,
  Invitation,
  InvitationInbox,
  ProfileItem,
  ProfileService,
} from "./types";

export class HelperApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code: string | null) {
    super(message);
    this.name = "HelperApiError";
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new Error("无法连接后端，请确认服务已启动。");
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const record = typeof body === "object" && body !== null ? body as Record<string, unknown> : {};
    throw new HelperApiError(
      typeof record.detail === "string" ? record.detail : `请求失败（${response.status}）`,
      response.status,
      typeof record.code === "string" ? record.code : null,
    );
  }
  return response.json() as Promise<T>;
}

function helperHeaders(helperId: number, json = false): HeadersInit {
  return {
    "X-Demo-User-Id": String(helperId),
    ...(json ? { "Content-Type": "application/json" } : {}),
  };
}

export function getHelperProfile(helperId: number): Promise<HelperProfile> {
  return request(`/api/demo/users/${helperId}/helper-profile`, { headers: helperHeaders(helperId) });
}

export function saveHelperProfile(helperId: number, items: ProfileItem[], services: ProfileService[]): Promise<HelperProfile> {
  return request(`/api/demo/users/${helperId}/helper-profile`, {
    method: "PUT",
    headers: helperHeaders(helperId, true),
    body: JSON.stringify({
      items: items.map(({ id, item_type, item_name, brand, model, active }) => ({
        id, item_type, item_name, brand, model, active,
      })),
      services,
    }),
  });
}

export function getDailyAvailability(helperId: number): Promise<DailyAvailability> {
  return request(`/api/demo/users/${helperId}/daily-availability`, { headers: helperHeaders(helperId) });
}

export function saveDailyAvailability(helperId: number, input: DailyAvailabilityData): Promise<DailyAvailability> {
  return request(`/api/demo/users/${helperId}/daily-availability`, {
    method: "PUT",
    headers: helperHeaders(helperId, true),
    body: JSON.stringify(input),
  });
}

export function getCampusLocations(): Promise<CampusLocation[]> {
  return request("/api/locations");
}

export function getInvitations(helperId: number): Promise<InvitationInbox> {
  return request(`/api/helpers/${helperId}/invitations`, { headers: helperHeaders(helperId) });
}

export function acceptInvitation(helperId: number, invitationId: number): Promise<unknown> {
  return request(`/api/invitations/${invitationId}/accept`, { method: "POST", headers: helperHeaders(helperId) });
}

export function declineInvitation(helperId: number, invitationId: number, reason: "declined" | "cannot_arrive"): Promise<Invitation> {
  return request(`/api/invitations/${invitationId}/decline`, {
    method: "POST",
    headers: helperHeaders(helperId, true),
    body: JSON.stringify({ reason }),
  });
}

export function proposeSubstitute(helperId: number, invitationId: number, itemId: number, note: string): Promise<Invitation> {
  return request(`/api/invitations/${invitationId}/propose-substitute`, {
    method: "POST",
    headers: helperHeaders(helperId, true),
    body: JSON.stringify({ item_id: itemId, note: note.trim() || null }),
  });
}

export function confirmInvitationCompletion(helperId: number, offerId: number): Promise<unknown> {
  return request(`/api/offers/${offerId}/confirm-completion`, {
    method: "POST",
    headers: helperHeaders(helperId),
  });
}

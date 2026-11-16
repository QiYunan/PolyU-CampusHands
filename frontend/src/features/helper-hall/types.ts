export type ItemType = "scientific_calculator" | "charger" | "adapter" | "stationery" | "umbrella" | "other";
export type ServiceCode = "moving" | "printing" | "tutoring" | "other";

export type ProfileItem = {
  id?: number;
  item_type: ItemType;
  item_name: string;
  brand: string | null;
  model: string | null;
  active: boolean;
  available?: boolean;
};

export type ProfileService = {
  id?: number;
  service_code: ServiceCode;
  service_name: string;
  active: boolean;
};

export type HelperProfile = {
  user_id: number;
  items: Array<ProfileItem & { id: number; available: boolean }>;
  services: Array<ProfileService & { id: number }>;
};

export type DailyAvailabilityData = {
  willing: boolean;
  available_from: string;
  available_until: string;
  campus_building: string;
  accepts_urgent: boolean;
  item_ids: number[];
  service_ids: number[];
};

export type DailyAvailability = {
  local_date: string;
  availability: DailyAvailabilityData | null;
  suggested_item_ids: number[];
  suggested_service_ids: number[];
};

export type CampusLocation = { code: string; label_zh: string; label_en: string };

export type Invitation = {
  id: number;
  batch_id: number;
  round_number: number;
  request_id: number;
  helper_id: number;
  helper_name: string;
  requester_name: string;
  category: "borrow" | "service";
  request_item_type: ItemType;
  need_summary: string;
  location: string;
  deadline: string;
  urgency: "normal" | "high";
  match_reason: "exact_model" | "exact_brand" | "compatible" | "service_exact";
  response_type: "direct" | "substitute";
  status: string;
  decline_reason: string | null;
  note: string | null;
  item_id: number | null;
  item_name: string | null;
  service_id: number | null;
  service_name: string | null;
  request_status: string;
  sent_at: string;
  responded_at: string | null;
  expires_at: string;
  offer_id: number | null;
  helper_confirmed: boolean;
};

export type InvitationInbox = {
  helper_id: number;
  pending: Invitation[];
  active: Invitation[];
  history: Invitation[];
};

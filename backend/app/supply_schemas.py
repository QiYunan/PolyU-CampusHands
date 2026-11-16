"""Public schemas for M07 Helper supply, search, and targeted invitations."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import ItemType, ServiceCode, as_utc, clean_preference


class ProfileItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = Field(default=None, gt=0)
    item_type: ItemType
    item_name: str = Field(min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    active: bool = True

    @field_validator("item_name", "brand", "model", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        return clean_preference(value)


class ProfileServiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = Field(default=None, gt=0)
    service_code: ServiceCode
    service_name: str = Field(min_length=1, max_length=120)
    active: bool = True

    @field_validator("service_name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return clean_preference(value)


class HelperProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProfileItemInput] = Field(default_factory=list, max_length=100)
    services: list[ProfileServiceInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        for values in (self.items, self.services):
            ids = [value.id for value in values if value.id is not None]
            if len(ids) != len(set(ids)):
                raise ValueError("Profile IDs must be unique")
        return self


class ProfileItemRead(ProfileItemInput):
    id: int


class ProfileServiceRead(ProfileServiceInput):
    id: int


class HelperProfileRead(BaseModel):
    user_id: int
    items: list[ProfileItemRead]
    services: list[ProfileServiceRead]


class DailyAvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    willing: bool
    available_from: datetime
    available_until: datetime
    campus_building: str = Field(min_length=1, max_length=80)
    accepts_urgent: bool = False
    item_ids: list[int] = Field(default_factory=list, max_length=100)
    service_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("available_from", "available_until")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Availability times must include a timezone")
        return value

    @field_validator("campus_building", mode="before")
    @classmethod
    def trim_building(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_lists_and_window(self):
        if self.available_from >= self.available_until:
            raise ValueError("available_from must be earlier than available_until")
        if any(value <= 0 for value in self.item_ids + self.service_ids):
            raise ValueError("Capability IDs must be positive")
        if len(self.item_ids) != len(set(self.item_ids)) or len(self.service_ids) != len(set(self.service_ids)):
            raise ValueError("Capability IDs must be unique")
        return self


class DailyAvailabilityData(BaseModel):
    willing: bool
    available_from: datetime
    available_until: datetime
    campus_building: str
    accepts_urgent: bool
    item_ids: list[int]
    service_ids: list[int]


class DailyAvailabilityRead(BaseModel):
    local_date: date
    availability: DailyAvailabilityData | None
    suggested_item_ids: list[int]
    suggested_service_ids: list[int]


MatchReason = Literal["exact_model", "exact_brand", "compatible", "service_exact"]
ReliabilityLevel = Literal["A", "B", "C", "New"]


class HelperSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: int = Field(gt=0)
    limit: int = Field(default=5, ge=3, le=5)


class HelperCandidateRead(BaseModel):
    helper_id: int
    display_name: str
    match_reason: MatchReason
    estimated_arrival_minutes: int
    available_from: datetime
    available_until: datetime
    reliability_level: ReliabilityLevel
    is_substitute: bool


class HelperSearchRead(BaseModel):
    request_id: int
    searched_at: datetime
    candidates: list[HelperCandidateRead]
    issue: str | None = None


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    helper_ids: list[int] = Field(min_length=1, max_length=3)

    @field_validator("helper_ids")
    @classmethod
    def unique_helpers(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values) or len(values) != len(set(values)):
            raise ValueError("helper_ids must contain unique positive IDs")
        return values


class InvitationDecline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["declined", "cannot_arrive"]


class SubstituteProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=300)

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value):
        return clean_preference(value) if value is not None else None


class InvitationRead(BaseModel):
    id: int
    batch_id: int
    round_number: int
    request_id: int
    helper_id: int
    helper_name: str
    requester_name: str
    category: Literal["borrow", "service"]
    need_summary: str
    location: str
    deadline: datetime
    urgency: Literal["normal", "high"]
    match_reason: MatchReason
    response_type: Literal["direct", "substitute"]
    status: str
    decline_reason: str | None
    note: str | None
    item_id: int | None
    item_name: str | None
    service_id: int | None
    service_name: str | None
    request_status: str
    sent_at: datetime
    responded_at: datetime | None
    expires_at: datetime
    offer_id: int | None = None
    helper_confirmed: bool = False


class InvitationInboxRead(BaseModel):
    helper_id: int
    pending: list[InvitationRead]
    active: list[InvitationRead]
    history: list[InvitationRead]


class InvitationBatchRead(BaseModel):
    id: int
    round_number: int
    status: str
    created_at: datetime
    closed_at: datetime | None
    invitations: list[InvitationRead]


class RequestInvitationsRead(BaseModel):
    request_id: int
    request_status: str
    batches: list[InvitationBatchRead]


def utc_value(value: datetime) -> datetime:
    return as_utc(value)

"""Public request input and output schemas."""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import AgentEvent, HelpOffer, HelpRequest


class ItemType(str, Enum):
    scientific_calculator = "scientific_calculator"
    charger = "charger"
    adapter = "adapter"
    stationery = "stationery"
    umbrella = "umbrella"
    other = "other"


ITEM_TYPE_SUMMARIES = {
    ItemType.scientific_calculator.value: "科学计算器",
    ItemType.charger.value: "充电器",
    ItemType.adapter.value: "转接头",
    ItemType.stationery.value: "文具",
    ItemType.umbrella.value: "雨伞",
    ItemType.other.value: "校园求助",
}


class SubstitutionPolicy(str, Enum):
    ask_before_substitute = "ask_before_substitute"
    exact_only = "exact_only"
    equivalent_ok = "equivalent_ok"


class ServiceCode(str, Enum):
    moving = "moving"
    printing = "printing"
    tutoring = "tutoring"
    other = "other"


class MatchingIssue(str, Enum):
    unknown_location = "unknown_location"
    no_item_inventory = "no_item_inventory"
    exact_preference_unavailable = "exact_preference_unavailable"
    alternatives_available_needs_confirmation = "alternatives_available_needs_confirmation"
    no_available_helper = "no_available_helper"
    unreachable_before_deadline = "unreachable_before_deadline"
    candidate_exhausted = "candidate_exhausted"


def clean_preference(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(unicodedata.normalize("NFKC", value).split()) or None


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["borrow", "service"] = "borrow"
    need_summary: str = Field(min_length=1, max_length=200)
    item_type: ItemType = ItemType.other
    service_code: ServiceCode | None = None
    service_name: str | None = Field(default=None, max_length=120)
    location: str = Field(min_length=1, max_length=80)
    deadline: datetime
    urgency: Literal["normal", "high"] = "normal"
    raw_text: str | None = Field(default=None, max_length=1000)
    preferred_brand: str | None = Field(default=None, max_length=80)
    preferred_model: str | None = Field(default=None, max_length=80)
    substitution_policy: SubstitutionPolicy | None = None

    @model_validator(mode="before")
    @classmethod
    def backfill_legacy_summary(cls, value):
        if not isinstance(value, dict):
            return value
        result = dict(value)
        summary = result.get("need_summary")
        item_type = result.get("item_type")
        if not isinstance(summary, str) or not summary.strip():
            if item_type is None:
                raise ValueError("need_summary is required")
            code = item_type.value if isinstance(item_type, ItemType) else str(item_type)
            result["need_summary"] = ITEM_TYPE_SUMMARIES.get(code, ITEM_TYPE_SUMMARIES[ItemType.other.value])
        if item_type is None:
            result["item_type"] = ItemType.other.value
        return result

    @model_validator(mode="after")
    def category_rules(self):
        if self.category == "service":
            self.item_type = ItemType.other
            self.service_code = self.service_code or ServiceCode.other
            self.service_name = clean_preference(self.service_name) or self.need_summary
            self.preferred_brand = None
            self.preferred_model = None
            self.substitution_policy = SubstitutionPolicy.equivalent_ok
        else:
            self.service_code = None
            self.service_name = None
        return self

    @field_validator("need_summary", mode="before")
    @classmethod
    def normalize_summary(cls, value):
        return " ".join(unicodedata.normalize("NFKC", value).split()) if isinstance(value, str) else value

    @field_validator("preferred_brand", "preferred_model", "service_name", mode="before")
    @classmethod
    def normalize_preference(cls, value):
        return clean_preference(value) if isinstance(value, str) or value is None else value

    @field_validator("location", mode="before")
    @classmethod
    def trim_location(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("raw_text", mode="before")
    @classmethod
    def trim_description(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("deadline")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value


class RequestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str | None = Field(default=None, min_length=1, max_length=80)
    deadline: datetime | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Provide a location or deadline")
        return self

    @field_validator("location", mode="before")
    @classmethod
    def trim_location(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("deadline")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("deadline must include a timezone")
        return value


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RequestRead(BaseModel):
    id: int
    requester_id: int
    category: Literal["borrow", "service"]
    raw_text: str | None
    need_summary: str
    item_type: ItemType
    service_code: ServiceCode | None = None
    service_name: str | None = None
    preferred_brand: str | None = None
    preferred_model: str | None = None
    substitution_policy: SubstitutionPolicy
    matching_issue: MatchingIssue | None = None
    location: str
    deadline: datetime
    urgency: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    events: list["EventRead"] = Field(default_factory=list)
    matched_helper: str | None = None
    handoff_location: str | None = None
    requester_confirmed: bool = False
    helper_confirmed: bool = False
    proposals: list["ProposalRead"] = Field(default_factory=list)
    helper_note: str | None = None
    offered_brand: str | None = None
    offered_model: str | None = None
    response_type: Literal["direct", "substitute"] | None = None

    @classmethod
    def from_record(cls, record: HelpRequest, **extra) -> "RequestRead":
        return cls(
            id=record.id,
            requester_id=record.requester_id,
            category=record.category,
            raw_text=record.raw_text,
            need_summary=record.need_summary,
            item_type=record.item_type,
            service_code=record.service_code,
            service_name=record.service_name,
            preferred_brand=record.preferred_brand,
            preferred_model=record.preferred_model,
            substitution_policy=record.substitution_policy,
            matching_issue=record.matching_issue,
            location=record.location,
            deadline=as_utc(record.deadline),
            urgency=record.urgency,
            status=record.status,
            created_at=as_utc(record.created_at),
            updated_at=as_utc(record.updated_at),
            **extra,
        )


class EventRead(BaseModel):
    id: int
    event_type: str
    public_message: str
    created_at: datetime

    @classmethod
    def from_record(cls, event: AgentEvent) -> "EventRead":
        return cls(id=event.id, event_type=event.event_type, public_message=event.public_message, created_at=as_utc(event.created_at))


class DemoRoleRead(BaseModel):
    id: int
    display_name: str
    role: Literal["requester", "helper"]


class ProposalRead(BaseModel):
    id: int
    helper_name: str
    help_note: str | None
    offered_brand: str | None
    offered_model: str | None
    status: Literal["proposed"]


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_confirmed: bool
    response_type: Literal["direct", "substitute"] = "direct"
    help_note: str | None = Field(default=None, max_length=300)
    offered_brand: str | None = Field(default=None, max_length=80)
    offered_model: str | None = Field(default=None, max_length=80)

    @field_validator("help_note", mode="before")
    @classmethod
    def normalize_note(cls, value):
        if value is None:
            return None
        return " ".join(unicodedata.normalize("NFKC", value).split()) or None

    @field_validator("offered_brand", "offered_model", mode="before")
    @classmethod
    def normalize_offered_preference(cls, value):
        return clean_preference(value) if isinstance(value, str) or value is None else value


class BoardViewerRead(BaseModel):
    id: int
    display_name: str


class BoardEntryRead(BaseModel):
    id: int
    requester_name: str
    category: Literal["borrow", "service"]
    need_summary: str
    item_type: ItemType
    location: str
    deadline: datetime
    urgency: Literal["normal", "high"]
    status: Literal["awaiting_response"]


class ClosedBoardRequestRead(BaseModel):
    id: int
    status: Literal["matched", "in_progress", "completed", "cancelled", "expired", "failed"]


class HelperBoardRead(BaseModel):
    viewer: BoardViewerRead
    requests: list[BoardEntryRead]
    dismissed_requests: list[BoardEntryRead]
    closed_requests: list[ClosedBoardRequestRead]


class OfferRead(BaseModel):
    id: int
    request_id: int
    helper_id: int
    category: Literal["borrow", "service"]
    need_summary: str
    item_type: ItemType | None
    item_name: str | None
    message: str | None = None
    response_type: Literal["direct", "substitute"]
    help_note: str | None = None
    offered_brand: str | None = None
    offered_model: str | None = None
    location: str
    deadline: datetime
    status: str
    request_status: str
    sent_at: datetime
    expires_at: datetime
    requester_confirmed: bool
    helper_confirmed: bool

    @classmethod
    def from_record(cls, offer: HelpOffer) -> "OfferRead":
        return cls(
            id=offer.id,
            request_id=offer.request_id,
            helper_id=offer.helper_id,
            category=offer.request.category,
            need_summary=offer.request.need_summary,
            item_type=offer.item.item_type if offer.item else None,
            item_name=offer.item.item_name if offer.item else None,
            message=offer.message,
            response_type=offer.response_type,
            help_note=offer.help_note,
            offered_brand=offer.offered_brand,
            offered_model=offer.offered_model,
            location=offer.request.location,
            deadline=as_utc(offer.request.deadline),
            status=offer.status,
            request_status=offer.request.status,
            sent_at=as_utc(offer.sent_at),
            expires_at=as_utc(offer.expires_at),
            requester_confirmed=offer.requester_confirmed_at is not None,
            helper_confirmed=offer.helper_confirmed_at is not None,
        )

"""Public request input and output schemas."""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import HelpRequest


class ItemType(str, Enum):
    scientific_calculator = "scientific_calculator"
    charger = "charger"
    adapter = "adapter"
    stationery = "stationery"
    umbrella = "umbrella"


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: ItemType
    location: str = Field(min_length=1, max_length=80)
    deadline: datetime
    raw_text: str | None = Field(default=None, max_length=1000)

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


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RequestRead(BaseModel):
    id: int
    requester_id: int
    category: str
    raw_text: str | None
    item_type: ItemType
    location: str
    deadline: datetime
    urgency: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: HelpRequest) -> "RequestRead":
        return cls(
            id=record.id,
            requester_id=record.requester_id,
            category=record.category,
            raw_text=record.raw_text,
            item_type=record.item_type,
            location=record.location,
            deadline=as_utc(record.deadline),
            urgency=record.urgency,
            status=record.status,
            created_at=as_utc(record.created_at),
            updated_at=as_utc(record.updated_at),
        )

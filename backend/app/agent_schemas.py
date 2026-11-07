"""Strict public and model-facing Agent contracts."""

import re
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import ItemType


def ambiguous_deadline_text(text: str) -> bool:
    """Do not turn competing or approximate times into an authoritative deadline."""
    relative_times = re.findall(r"\d{1,4}\s*分钟后", text)
    return len(relative_times) > 1 or bool(re.search(r"一会儿|稍后|不确定|大概|左右|可能|\d{1,4}\s*分钟后\s*(?:或|或者|还是)", text))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Urgency(str, Enum):
    normal = "normal"
    high = "high"


class ParsedFields(StrictModel):
    category: Literal["borrow"] = "borrow"
    item_type: ItemType | None = None
    location: str | None = Field(default=None, max_length=80)
    deadline_in_minutes: int | None = Field(default=None, gt=0, le=10080)
    deadline_at: datetime | None = None
    urgency: Urgency | None = None

    @model_validator(mode="after")
    def one_deadline(self):
        if self.deadline_in_minutes is not None and self.deadline_at is not None:
            raise ValueError("Provide only one deadline format")
        return self


class DraftCreate(StrictModel):
    raw_text: str = Field(min_length=1, max_length=1000)


class DraftClarify(StrictModel):
    text: str = Field(min_length=1, max_length=1000)


class DraftEdit(StrictModel):
    item_type: ItemType | None = None
    location: str | None = Field(default=None, max_length=80)
    deadline: datetime | None = None
    urgency: Urgency | None = None


class DraftRead(StrictModel):
    id: int
    raw_text: str
    item_type: ItemType | None
    location: str | None
    deadline: datetime | None
    urgency: Urgency | None
    missing_fields: list[Literal["item_type", "location", "deadline"]]
    public_question: str | None
    status: Literal["collecting_details", "ready", "confirmed"]
    request_id: int | None
    provider: str | None = None
    fallback_active: bool = False


class ToolArgs(StrictModel):
    request_id: int = Field(gt=0)


class OfferToolArgs(ToolArgs):
    message: str | None = Field(default=None, min_length=1, max_length=300)


class DraftToolArgs(StrictModel):
    draft_id: int = Field(gt=0)


class ClarificationToolArgs(DraftToolArgs):
    missing_fields: list[Literal["item_type", "location", "deadline"]]


class ActionProposal(StrictModel):
    name: Literal["ask_clarification", "create_help_request", "search_helpers", "send_help_offer", "observe_request", "wait_for_response", "finish"]
    arguments: dict = Field(default_factory=dict)


class AgentRunRead(StrictModel):
    request_id: int
    status: str
    step_count: int
    provider: str | None
    fallback_active: bool
    message: str
    action_committed: bool = False
    validated_actions: list[Literal["search_helpers", "send_help_offer"]] = Field(default_factory=list)

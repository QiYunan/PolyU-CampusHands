"""Strict public and model-facing Agent contracts."""

import re
import unicodedata
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.campus_locations import normalize_location
from app.schemas import ItemType, MatchingIssue, SubstitutionPolicy, clean_preference


RELATIVE_DEADLINE = r"\d{1,4}\s*分钟(?:之)?后"
LOCATION_CUE = re.compile(r"(?:(?<![现正存])在|於|于|交接地点\s*[:：]?|地点\s*[:：]?|更改为|改成|改为|换到|\bat\s+)([^，,。；;!?！？]{1,50})", re.I)


def location_from_text(text: str) -> str | None:
    """Find a stated place, preserving an unknown name for clarification."""
    for match in LOCATION_CUE.finditer(text):
        candidate = match.group(1).strip()
        if re.match(r"\d{1,4}\s*分钟", candidate):
            continue
        for length in range(len(candidate), 0, -1):
            canonical = normalize_location(candidate[:length].strip())
            if canonical:
                return canonical
        unknown = re.split(r"交接|考试|想借|需要|借用|借一|之前|之后|以后", candidate, maxsplit=1)[0].strip()
        if unknown:
            return unknown
    explicit = re.search(r"Block\s+[A-Z]{1,2}\b|Library(?![A-Za-z])|图书馆|圖書館|[A-Z]{1,2}[栋棟座楼樓]", text, re.I)
    if explicit:
        return normalize_location(explicit.group(0))
    return None


def ambiguous_deadline_text(text: str) -> bool:
    """Do not turn competing or approximate times into an authoritative deadline."""
    relative_times = re.findall(RELATIVE_DEADLINE, text)
    return len(relative_times) > 1 or bool(re.search(rf"一会儿|稍后|不确定|大概|左右|可能|{RELATIVE_DEADLINE}\s*(?:或|或者|还是)", text))


def _fold(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())


def preference_is_grounded(value: str | None, text: str, known: str | None = None) -> bool:
    """Only accept a model's brand or model when the requester supplied it."""
    if value is None:
        return True
    folded = _fold(value)
    if not folded:
        return False
    if known and folded == _fold(known):
        return True
    source = _fold(text)
    if folded in source:
        return True
    casio_aliases = {"casio", "卡西欧", "卡西歐"}
    return folded in casio_aliases and any(alias in source for alias in casio_aliases)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Urgency(str, Enum):
    normal = "normal"
    high = "high"


class ParsedFields(StrictModel):
    category: Literal["borrow", "service"]
    need_summary: str | None = Field(default=None, max_length=200)
    item_type: ItemType | None = None
    preferred_brand: str | None = Field(default=None, max_length=80)
    preferred_model: str | None = Field(default=None, max_length=80)
    substitution_policy: Literal["exact_only"] | None = None
    location: str | None = Field(default=None, max_length=80)
    deadline_in_minutes: int | None = Field(default=None, gt=0, le=10080)
    deadline_at: datetime | None = None
    urgency: Urgency | None = None

    @field_validator("preferred_brand", "preferred_model", mode="before")
    @classmethod
    def clean_preference(cls, value: str | None) -> str | None:
        return clean_preference(value) if isinstance(value, str) or value is None else value

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
    category: Literal["borrow", "service"] | None = None
    need_summary: str | None = Field(default=None, max_length=200)
    item_type: ItemType | None = None
    preferred_brand: str | None = Field(default=None, max_length=80)
    preferred_model: str | None = Field(default=None, max_length=80)
    substitution_policy: SubstitutionPolicy | None = None
    location: str | None = Field(default=None, max_length=80)
    deadline: datetime | None = None
    urgency: Urgency | None = None

    @field_validator("preferred_brand", "preferred_model", mode="before")
    @classmethod
    def clean_preference(cls, value: str | None) -> str | None:
        return clean_preference(value) if isinstance(value, str) or value is None else value


class DraftConfirm(StrictModel):
    """The requester's complete current form, applied atomically at confirmation."""

    category: Literal["borrow", "service"]
    need_summary: str | None = Field(max_length=200)
    item_type: ItemType | None
    preferred_brand: str | None = Field(max_length=80)
    preferred_model: str | None = Field(max_length=80)
    substitution_policy: SubstitutionPolicy
    location: str | None = Field(max_length=80)
    deadline: datetime | None
    urgency: Urgency

    @field_validator("preferred_brand", "preferred_model", mode="before")
    @classmethod
    def clean_preference(cls, value: str | None) -> str | None:
        return clean_preference(value) if isinstance(value, str) or value is None else value


class DraftRead(StrictModel):
    id: int
    raw_text: str
    category: Literal["borrow", "service"]
    need_summary: str | None
    item_type: ItemType | None
    preferred_brand: str | None
    preferred_model: str | None
    substitution_policy: SubstitutionPolicy
    matching_issue: MatchingIssue | None = None
    location: str | None
    deadline: datetime | None
    urgency: Urgency | None
    missing_fields: list[Literal["need_summary", "location", "deadline"]]
    public_question: str | None
    status: Literal["collecting_details", "ready", "confirmed"]
    request_id: int | None
    provider: str | None = None
    fallback_active: bool = False


class ToolArgs(StrictModel):
    request_id: int = Field(gt=0)


class PublishToolArgs(ToolArgs):
    pass


class DraftToolArgs(StrictModel):
    draft_id: int = Field(gt=0)


class ClarificationToolArgs(DraftToolArgs):
    missing_fields: list[Literal["need_summary", "location", "deadline"]]


class ActionProposal(StrictModel):
    name: Literal["ask_clarification", "create_help_request", "search_helpers", "publish_request", "observe_request", "wait_for_response", "finish"]
    arguments: dict = Field(default_factory=dict)


class AgentRunRead(StrictModel):
    request_id: int
    status: str
    matching_issue: MatchingIssue | None = None
    step_count: int
    provider: str | None
    fallback_active: bool
    message: str
    action_committed: bool = False
    validated_actions: list[Literal["search_helpers", "publish_request"]] = Field(default_factory=list)

"""Only public, server-owned facts may cross the realtime transport."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import AgentEvent, HelpOffer, HelpRequest
from app.schemas import as_utc


class RealtimeNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    event_id: int = Field(gt=0)
    event_type: str = Field(min_length=1, max_length=64)
    resource_kind: Literal["request", "offer"]
    resource_id: int = Field(gt=0)
    status: str = Field(min_length=1, max_length=32)
    public_message: str = Field(max_length=300)
    created_at: datetime


def request_notice(event: AgentEvent, request: HelpRequest) -> RealtimeNotice:
    return RealtimeNotice(
        event_id=event.id, event_type=event.event_type,
        resource_kind="request", resource_id=request.id,
        status=request.status, public_message=event.public_message,
        created_at=as_utc(event.created_at),
    )


def offer_notice(event: AgentEvent, offer: HelpOffer) -> RealtimeNotice:
    # A Helper receives only an invalidation for their own Offer. The HTTP GET
    # supplies the complete authorized snapshot after this notification.
    return RealtimeNotice(
        event_id=event.id, event_type="inbox_changed",
        resource_kind="offer", resource_id=offer.id,
        status=offer.status, public_message="邀请状态已更新",
        created_at=as_utc(event.created_at),
    )

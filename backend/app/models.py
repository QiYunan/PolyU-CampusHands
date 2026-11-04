"""Milestone 01 persistent entities."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utc_now_naive


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    campus_building: Mapped[str] = mapped_column(String(80), nullable=False)
    availability_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    reliability_score: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    requests: Mapped[list["HelpRequest"]] = relationship(back_populates="requester")
    items: Mapped[list["UserItem"]] = relationship(back_populates="owner")


class HelpRequest(Base):
    __tablename__ = "help_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="borrow")
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    location: Mapped[str] = mapped_column(String(80), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    urgency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive)
    requester: Mapped[User] = relationship(back_populates="requests")
    offers: Mapped[list["HelpOffer"]] = relationship(back_populates="request")
    events: Mapped[list["AgentEvent"]] = relationship(back_populates="request")


class UserItem(Base):
    __tablename__ = "user_items"
    __table_args__ = (UniqueConstraint("user_id", "item_type", "item_name", name="uq_user_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    item_name: Mapped[str] = mapped_column(String(120), nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner: Mapped[User] = relationship(back_populates="items")


class HelpOffer(Base):
    __tablename__ = "help_offers"
    __table_args__ = (UniqueConstraint("request_id", "helper_id", name="uq_offer_request_helper"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("help_requests.id"), nullable=False)
    helper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("user_items.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    requester_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    helper_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    request: Mapped[HelpRequest] = relationship(back_populates="offers")
    helper: Mapped[User] = relationship()
    item: Mapped[UserItem] = relationship()


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("help_requests.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    public_message: Mapped[str] = mapped_column(String(300), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    request: Mapped[HelpRequest] = relationship(back_populates="events")

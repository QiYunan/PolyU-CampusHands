"""Milestone 01 persistent entities."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
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

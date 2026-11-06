"""Persistent clarification drafts; formal requests retain their required fields."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.agent_schemas import DraftEdit, DraftRead, ParsedFields, ambiguous_deadline_text
from app.models import AgentEvent, HelpRequest, HelpRequestDraft
from app.privacy import public_text
from app.schemas import RequestCreate, as_utc
from app.services import Forbidden, InvalidDeadline, NotFound, write_transaction
from app.providers.fallback import ProviderRouter


def _require_draft(session: Session, draft_id: int, actor_id: int) -> HelpRequestDraft:
    draft = session.get(HelpRequestDraft, draft_id)
    if draft is None:
        raise NotFound("Draft not found")
    if draft.requester_id != actor_id or actor_id != 1:
        raise Forbidden("Only the requester can access this draft")
    return draft


def _missing(draft: HelpRequestDraft) -> list[str]:
    return [name for name in ("item_type", "location", "deadline") if not getattr(draft, name)]


def _question(missing: list[str]) -> str | None:
    labels = {"item_type": "物品类型", "location": "交接地点", "deadline": "最晚需要时间"}
    return "请补充" + "和".join(labels[field] for field in missing) + "。" if missing else None


def _refresh_status(draft: HelpRequestDraft) -> None:
    missing = _missing(draft)
    draft.missing_fields_json = json.dumps(missing)
    draft.public_question = _question(missing)
    draft.status = "collecting_details" if missing else "ready"


def _deadline(parsed: ParsedFields, now: datetime) -> datetime | None:
    if parsed.deadline_in_minutes is not None:
        return now + timedelta(minutes=parsed.deadline_in_minutes)
    if parsed.deadline_at is not None:
        value = parsed.deadline_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo("Asia/Hong_Kong"))
        return value.astimezone(timezone.utc)
    return None


def draft_view(draft: HelpRequestDraft, router: ProviderRouter | None = None) -> DraftRead:
    return DraftRead(
        id=draft.id, raw_text=draft.raw_text, item_type=draft.item_type, location=draft.location,
        deadline=as_utc(draft.deadline) if draft.deadline else None, urgency=draft.urgency,
        missing_fields=json.loads(draft.missing_fields_json), public_question=draft.public_question,
        status=draft.status, request_id=draft.request_id,
        provider=router.active if router else None, fallback_active=router.fallback_active if router else False,
    )


async def create_draft(session: Session, router: ProviderRouter, text: str, actor_id: int, now: datetime | None = None) -> DraftRead:
    if actor_id != 1:
        raise Forbidden("Only Alice can create a draft in Demo Mode")
    current = now or datetime.now(timezone.utc)
    clean = public_text(text)
    parsed = await router.parse(clean, current, {})
    deadline = _deadline(parsed, current)
    if deadline and deadline <= current:
        raise InvalidDeadline("deadline must be in the future")
    with write_transaction(session):
        draft = HelpRequestDraft(requester_id=actor_id, raw_text=clean, item_type=parsed.item_type.value if parsed.item_type else None,
            location=parsed.location.strip() or None if parsed.location else None,
            deadline=deadline.replace(tzinfo=None) if deadline else None, urgency=parsed.urgency.value if parsed.urgency else None,
            status="collecting_details")
        _refresh_status(draft)
        draft.public_turns_json = json.dumps([{"role": "user", "text": clean}] + ([{"role": "assistant", "text": draft.public_question}] if draft.public_question else []), ensure_ascii=False)
        session.add(draft)
        session.flush()
    return draft_view(draft, router)


async def clarify_draft(session: Session, router: ProviderRouter, draft_id: int, text: str, actor_id: int, now: datetime | None = None) -> DraftRead:
    draft = _require_draft(session, draft_id, actor_id)
    if draft.status == "confirmed":
        from app.state_machine import StateConflict
        raise StateConflict("Draft is already confirmed")
    current = now or datetime.now(timezone.utc)
    clean = public_text(text)
    known = {"item_type": draft.item_type, "location": draft.location, "deadline": as_utc(draft.deadline).isoformat() if draft.deadline else None, "urgency": draft.urgency}
    parsed = await router.parse(clean, current, known)
    deadline = None if ambiguous_deadline_text(clean) else _deadline(parsed, current) or (as_utc(draft.deadline) if draft.deadline else None)
    if deadline and deadline <= current:
        raise InvalidDeadline("deadline must be in the future")
    session.rollback()  # Parsing was read-only; acquire the SQLite write lock afresh.
    with write_transaction(session):
        draft = _require_draft(session, draft_id, actor_id)
        draft.item_type = parsed.item_type.value if parsed.item_type else draft.item_type
        draft.location = parsed.location.strip() or None if parsed.location else draft.location
        draft.deadline = deadline.replace(tzinfo=None) if deadline else None
        draft.urgency = parsed.urgency.value if parsed.urgency else draft.urgency
        turns = json.loads(draft.public_turns_json)
        turns.append({"role": "user", "text": clean})
        _refresh_status(draft)
        if draft.public_question:
            turns.append({"role": "assistant", "text": draft.public_question})
        draft.public_turns_json = json.dumps(turns, ensure_ascii=False)
    return draft_view(draft, router)


def edit_draft(session: Session, draft_id: int, edits: DraftEdit, actor_id: int) -> DraftRead:
    from app.state_machine import StateConflict
    with write_transaction(session):
        draft = _require_draft(session, draft_id, actor_id)
        if draft.status == "confirmed":
            raise StateConflict("Draft is already confirmed")
        values = edits.model_dump(exclude_unset=True)
        for name, value in values.items():
            if name == "deadline" and value is not None:
                if value.tzinfo is None or value.utcoffset() is None:
                    raise InvalidDeadline("deadline must include timezone")
                if value <= datetime.now(timezone.utc):
                    raise InvalidDeadline("deadline must be in the future")
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            if name == "location" and value is not None:
                value = public_text(value)[:80] or None
            if name in {"item_type", "urgency"} and value is not None:
                value = value.value
            setattr(draft, name, value)
        _refresh_status(draft)
    return draft_view(draft)


def confirm_draft(session: Session, draft_id: int, actor_id: int) -> HelpRequest:
    from app.state_machine import StateConflict
    with write_transaction(session):
        draft = _require_draft(session, draft_id, actor_id)
        if draft.request_id is not None:
            return session.get(HelpRequest, draft.request_id)
        if draft.status != "ready" or _missing(draft):
            raise StateConflict("Complete and confirm all required fields first")
        payload = RequestCreate(item_type=draft.item_type, location=draft.location, deadline=as_utc(draft.deadline), raw_text=draft.raw_text)
        if payload.deadline <= datetime.now(timezone.utc):
            raise InvalidDeadline("deadline must be in the future")
        request = HelpRequest(requester_id=actor_id, category="borrow", raw_text=payload.raw_text,
            item_type=payload.item_type.value, location=payload.location,
            deadline=payload.deadline.astimezone(timezone.utc).replace(tzinfo=None),
            urgency=draft.urgency, status="draft")
        session.add(request)
        session.flush()
        draft.request_id = request.id
        draft.status = "confirmed"
        draft.public_question = None
        session.add(AgentEvent(request_id=request.id, event_type="request_parsed", public_message="已解析并确认借物请求", metadata_json="{}", dedupe_key=f"{request.id}:request_parsed:draft"))
    return request

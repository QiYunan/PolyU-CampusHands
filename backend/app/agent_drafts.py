"""Persistent clarification drafts; formal requests retain their required fields."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.agent_schemas import DraftConfirm, DraftEdit, DraftRead, ParsedFields, ambiguous_deadline_text
from app.campus_locations import normalize_location
from app.models import AgentEvent, HelpRequest, HelpRequestDraft
from app.privacy import public_text
from app.schemas import ItemType, MatchingIssue, RequestCreate, SubstitutionPolicy, as_utc, clean_preference
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
    return [name for name in ("need_summary", "location", "deadline")
            if not getattr(draft, name) or (name == "location" and normalize_location(draft.location) is None)]


def _canonical_or_raw(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    return normalize_location(stripped) or stripped or None


def _question(missing: list[str], invalid_location: bool = False) -> str | None:
    labels = {"need_summary": "需求摘要", "location": "交接地点", "deadline": "最晚需要时间"}
    if invalid_location and missing == ["location"]:
        return "无法识别交接地点，请提供主校园建筑名称或代码。"
    return "请补充" + "和".join(labels[field] for field in missing) + "。" if missing else None


def _refresh_status(draft: HelpRequestDraft) -> None:
    missing = _missing(draft)
    draft.missing_fields_json = json.dumps(missing)
    draft.public_question = _question(missing, bool(draft.location and normalize_location(draft.location) is None))
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


def _clean_summary(value: str | None) -> str | None:
    if value is None:
        return None
    return public_text(value)[:200].strip() or None


def _apply_form_values(draft: HelpRequestDraft, values: dict, now: datetime) -> None:
    """Apply user-visible fields to a draft while preserving request invariants."""
    had_preference = bool(draft.preferred_brand or draft.preferred_model)
    policy_provided = "substitution_policy" in values and values["substitution_policy"] is not None
    for name, value in values.items():
        if name == "category":
            if value is not None:
                draft.category = value
            continue
        if name == "need_summary":
            draft.need_summary = _clean_summary(value)
            continue
        if name == "deadline" and value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise InvalidDeadline("deadline must include timezone")
            if value <= now:
                raise InvalidDeadline("deadline must be in the future")
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        if name == "location" and value is not None:
            value = _canonical_or_raw(public_text(value)[:80])
        if name in {"preferred_brand", "preferred_model"}:
            value = clean_preference(value)
        if name == "substitution_policy":
            if value is None:
                continue
            value = value.value
        if name in {"item_type", "urgency"} and value is not None:
            value = value.value
        setattr(draft, name, value)

    draft.category = draft.category or "borrow"
    if draft.category == "service":
        draft.item_type = ItemType.other.value
        draft.preferred_brand = None
        draft.preferred_model = None
        draft.substitution_policy = SubstitutionPolicy.equivalent_ok.value
        return

    draft.item_type = draft.item_type or ItemType.other.value
    has_preference = bool(draft.preferred_brand or draft.preferred_model)
    if not has_preference:
        draft.substitution_policy = SubstitutionPolicy.equivalent_ok.value
    elif not policy_provided and not had_preference:
        draft.substitution_policy = SubstitutionPolicy.ask_before_substitute.value


def draft_view(draft: HelpRequestDraft, router: ProviderRouter | None = None) -> DraftRead:
    return DraftRead(
        id=draft.id, raw_text=draft.raw_text, category=draft.category or "borrow",
        need_summary=draft.need_summary, item_type=draft.item_type,
        preferred_brand=draft.preferred_brand, preferred_model=draft.preferred_model,
        substitution_policy=draft.substitution_policy or SubstitutionPolicy.equivalent_ok,
        matching_issue=MatchingIssue.unknown_location if draft.location and normalize_location(draft.location) is None else None,
        location=draft.location,
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
        is_service = parsed.category == "service"
        preferred_brand = None if is_service else clean_preference(parsed.preferred_brand)
        preferred_model = None if is_service else clean_preference(parsed.preferred_model)
        draft = HelpRequestDraft(requester_id=actor_id, raw_text=clean, category=parsed.category,
            need_summary=_clean_summary(parsed.need_summary),
            item_type=ItemType.other.value if is_service or parsed.item_type is None else parsed.item_type.value,
            location=_canonical_or_raw(parsed.location),
            preferred_brand=preferred_brand, preferred_model=preferred_model,
            substitution_policy=(SubstitutionPolicy.equivalent_ok if is_service or not (preferred_brand or preferred_model)
                                 else SubstitutionPolicy.exact_only if parsed.substitution_policy == "exact_only"
                                 else SubstitutionPolicy.ask_before_substitute).value,
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
    known = {"category": draft.category, "need_summary": draft.need_summary, "item_type": draft.item_type,
             "location": draft.location, "deadline": as_utc(draft.deadline).isoformat() if draft.deadline else None,
             "urgency": draft.urgency, "preferred_brand": draft.preferred_brand, "preferred_model": draft.preferred_model,
             "substitution_policy": draft.substitution_policy}
    parsed = await router.parse(clean, current, known)
    deadline = None if ambiguous_deadline_text(clean) else _deadline(parsed, current) or (as_utc(draft.deadline) if draft.deadline else None)
    if deadline and deadline <= current:
        raise InvalidDeadline("deadline must be in the future")
    session.rollback()  # Parsing was read-only; acquire the SQLite write lock afresh.
    with write_transaction(session):
        draft = _require_draft(session, draft_id, actor_id)
        draft.category = parsed.category
        draft.need_summary = _clean_summary(parsed.need_summary) or draft.need_summary
        draft.item_type = parsed.item_type.value if parsed.item_type else draft.item_type or ItemType.other.value
        draft.location = _canonical_or_raw(parsed.location) if parsed.location else draft.location
        if draft.category == "service":
            draft.item_type = ItemType.other.value
            draft.preferred_brand = None
            draft.preferred_model = None
            draft.substitution_policy = SubstitutionPolicy.equivalent_ok.value
        else:
            had_preference = bool(draft.preferred_brand or draft.preferred_model)
            draft.preferred_brand = clean_preference(parsed.preferred_brand) if parsed.preferred_brand else draft.preferred_brand
            draft.preferred_model = clean_preference(parsed.preferred_model) if parsed.preferred_model else draft.preferred_model
            if parsed.substitution_policy == "exact_only":
                draft.substitution_policy = SubstitutionPolicy.exact_only.value
            elif not had_preference and (draft.preferred_brand or draft.preferred_model):
                draft.substitution_policy = SubstitutionPolicy.ask_before_substitute.value
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
        _apply_form_values(draft, edits.model_dump(exclude_unset=True), datetime.now(timezone.utc))
        _refresh_status(draft)
    return draft_view(draft)


def confirm_draft(session: Session, draft_id: int, form: DraftConfirm, actor_id: int) -> HelpRequest:
    from app.state_machine import StateConflict
    with write_transaction(session):
        draft = _require_draft(session, draft_id, actor_id)
        if draft.request_id is not None:
            return session.get(HelpRequest, draft.request_id)
        current = datetime.now(timezone.utc)
        _apply_form_values(draft, form.model_dump(), current)
        _refresh_status(draft)
        if draft.status != "ready" or _missing(draft):
            raise StateConflict("Complete and confirm all required fields first")
        payload = RequestCreate(category=draft.category, need_summary=draft.need_summary,
                                item_type=draft.item_type, location=normalize_location(draft.location),
                                deadline=as_utc(draft.deadline), raw_text=draft.raw_text,
                                preferred_brand=draft.preferred_brand, preferred_model=draft.preferred_model,
                                substitution_policy=draft.substitution_policy or SubstitutionPolicy.equivalent_ok,
                                urgency=draft.urgency)
        if payload.deadline <= current:
            raise InvalidDeadline("deadline must be in the future")
        request = HelpRequest(requester_id=actor_id, category=payload.category, need_summary=payload.need_summary,
            raw_text=payload.raw_text, item_type=payload.item_type.value, location=payload.location,
            preferred_brand=payload.preferred_brand, preferred_model=payload.preferred_model,
            substitution_policy=(payload.substitution_policy or SubstitutionPolicy.equivalent_ok).value,
            deadline=payload.deadline.astimezone(timezone.utc).replace(tzinfo=None),
            urgency=draft.urgency, status="draft")
        session.add(request)
        session.flush()
        draft.request_id = request.id
        draft.status = "confirmed"
        draft.public_question = None
        session.add(AgentEvent(request_id=request.id, event_type="request_parsed", public_message="已解析并确认校园求助", metadata_json="{}", dedupe_key=f"{request.id}:request_parsed:draft"))
    return request

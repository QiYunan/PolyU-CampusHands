"""Local allowlist. Every mutating tool delegates to deterministic services."""

from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent_schemas import ActionProposal, ClarificationToolArgs, DraftToolArgs, OfferToolArgs, ToolArgs
from app.matching import rank_candidates
from app.services import Forbidden, get_request_for_actor, request_view, start_search


TOOL_SCHEMAS = {
    "ask_clarification": ClarificationToolArgs,
    "create_help_request": DraftToolArgs,
    "search_helpers": ToolArgs,
    "send_help_offer": OfferToolArgs,
    "observe_request": ToolArgs,
    "wait_for_response": ToolArgs,
    "finish": ToolArgs,
}


class InvalidAgentAction(ValueError):
    pass


def validate_action(proposal: ActionProposal, allowed: list[str], expected_id: int) -> dict:
    if proposal.name not in TOOL_SCHEMAS or proposal.name not in allowed:
        raise InvalidAgentAction("Tool is not allowed in this state")
    try:
        arguments = TOOL_SCHEMAS[proposal.name].model_validate(proposal.arguments).model_dump()
    except ValidationError:
        raise InvalidAgentAction("Invalid tool arguments") from None
    if arguments.get("request_id", arguments.get("draft_id")) != expected_id:
        raise InvalidAgentAction("Tool targets another record")
    return arguments


def observe(session: Session, request_id: int, actor_id: int) -> dict:
    request = get_request_for_actor(session, request_id, actor_id)
    view = request_view(session, request)
    result = {"request_id": request.id, "status": request.status, "item_type": request.item_type, "location": request.location, "event_types": [event.event_type for event in view.events]}
    if request.status == "draft":
        result["candidate_count"] = len(rank_candidates(session, request, datetime.now(timezone.utc).replace(tzinfo=None)))
    return result


def execute(session: Session, proposal: ActionProposal, allowed: list[str], request_id: int, actor_id: int) -> tuple[dict, bool]:
    arguments = validate_action(proposal, allowed, request_id)
    if actor_id != 1:
        raise Forbidden("Only Alice can run the Agent in Demo Mode")
    if proposal.name == "send_help_offer":
        message = arguments.get("message")
        if message and (any(term in message for term in ("已接受", "已完成", "电话", "手机")) or any(char.isdigit() for char in message)):
            raise InvalidAgentAction("Invitation contains unsupported facts")
        session.rollback()  # Release the read transaction before BEGIN IMMEDIATE.
        start_search(session, request_id, actor_id, offer_message=message)
        return observe(session, request_id, actor_id), True
    if proposal.name == "search_helpers":
        return observe(session, request_id, actor_id), False
    # wait_for_response and finish are immediate loop exits, never business transitions.
    return observe(session, request_id, actor_id), False

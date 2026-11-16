"""Local allowlist. Every mutating tool delegates to deterministic services."""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent_schemas import ActionProposal, ClarificationToolArgs, DraftToolArgs, PublishToolArgs, ToolArgs
from app.services import Forbidden, get_request_for_actor, precheck_publication, publish_request


TOOL_SCHEMAS = {
    "ask_clarification": ClarificationToolArgs,
    "create_help_request": DraftToolArgs,
    "search_helpers": ToolArgs,
    "publish_request": PublishToolArgs,
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
    # Model-facing observations contain no candidate, inventory, location or score data.
    return {"request_id": request.id, "status": request.status, "matching_issue": request.matching_issue}


def execute(session: Session, proposal: ActionProposal, allowed: list[str], request_id: int, actor_id: int) -> tuple[dict, bool]:
    validate_action(proposal, allowed, request_id)
    if actor_id != 1:
        raise Forbidden("Only Alice can run the Agent in Demo Mode")
    if proposal.name == "publish_request":
        before = observe(session, request_id, actor_id)
        session.rollback()  # Release the read transaction before BEGIN IMMEDIATE.
        publish_request(session, request_id, actor_id)
        after = observe(session, request_id, actor_id)
        return after, after != before
    if proposal.name == "search_helpers":
        # A read-only service preflight returns only the same safe problem code
        # that the requester may see; no Helper identity, count or item enters
        # the model observation.
        issue = precheck_publication(session, request_id, actor_id)
        state = observe(session, request_id, actor_id)
        return {**state, "matching_issue": issue}, False
    # wait_for_response and finish are immediate loop exits, never business transitions.
    return observe(session, request_id, actor_id), False

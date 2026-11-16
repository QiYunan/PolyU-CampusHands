"""Finite action-observation loop around the existing BorrowLoop service."""

from sqlalchemy.orm import Session

from app.agent_schemas import AgentRunRead
from app.agent_tools import execute, observe
from app.providers.base import LLMUnavailable
from app.providers.fallback import ProviderRouter
from app.state_machine import StateConflict


MAX_STEPS = 6
MAX_MODEL_CALLS = 3
TERMINAL = {"completed", "cancelled", "expired", "failed"}

ISSUE_MESSAGES = {
    "unknown_location": "请更正交接地点。",
    "no_item_inventory": "当前无法完成该物品请求。",
    "exact_preference_unavailable": "当前无法按指定品牌或型号匹配。",
    "alternatives_available_needs_confirmation": "如接受同类兼容物品，请先明确确认。",
    "no_available_helper": "当前暂无可联系的帮助者，请稍后重试。",
    "unreachable_before_deadline": "预计无法在截止时间前完成交接，请调整时间或地点。",
    "candidate_exhausted": "已尝试可联系的帮助者，请重新创建请求。",
}


async def run_search(session: Session, router: ProviderRouter, request_id: int, actor_id: int) -> AgentRunRead:
    observation = observe(session, request_id, actor_id)
    if observation["status"] not in {"draft", "awaiting_response"} and not (observation["status"] == "searching" and observation["matching_issue"]):
        raise StateConflict("Agent publication can start only from a draft, published request or paused legacy search")
    committed = False
    validated_actions: list[str] = []
    steps = 0
    model_calls = 0
    searched_helpers = False
    while steps < MAX_STEPS and model_calls < MAX_MODEL_CALLS:
        status = observation["status"]
        if status in TERMINAL or status not in {"draft", "searching", "awaiting_response"}:
            break
        allowed = (["publish_request", "finish"] if searched_helpers else
                   ["search_helpers", "publish_request", "finish"]) if status in {"draft", "searching"} else ["wait_for_response", "finish"]
        try:
            proposal = await router.choose(observation, allowed)
            model_calls += 1
            observation, did_write = execute(session, proposal, allowed, request_id, actor_id)
            committed = committed or did_write
            if proposal.name in {"search_helpers", "publish_request"}:
                validated_actions.append(proposal.name)
            if proposal.name == "search_helpers":
                searched_helpers = True
        except LLMUnavailable:
            if not committed:
                raise
            observation = observe(session, request_id, actor_id)
            return AgentRunRead(request_id=request_id, status=observation["status"], matching_issue=observation["matching_issue"], step_count=steps,
                provider=router.active, fallback_active=router.fallback_active,
                message="业务操作已保存；模型暂不可用，请刷新查看状态。", action_committed=True,
                validated_actions=validated_actions)
        steps += 1
        if proposal.name in {"wait_for_response", "finish"} or (proposal.name == "publish_request" and observation["matching_issue"]):
            break
    observation = observe(session, request_id, actor_id)
    message = ("请求已发布，等待帮助者主动认领" if observation["status"] == "awaiting_response"
               else ISSUE_MESSAGES.get(observation["matching_issue"], "已读取服务端状态"))
    return AgentRunRead(request_id=request_id, status=observation["status"], matching_issue=observation["matching_issue"], step_count=steps,
        provider=router.active, fallback_active=router.fallback_active, message=message,
        action_committed=committed, validated_actions=validated_actions)


async def run_observation(session: Session, router: ProviderRouter, request_id: int, actor_id: int) -> AgentRunRead:
    observation = observe(session, request_id, actor_id)
    allowed = ["wait_for_response", "finish"] if observation["status"] == "awaiting_response" else ["finish"]
    proposal = await router.choose(observation, allowed)
    observation, _ = execute(session, proposal, allowed, request_id, actor_id)
    # The explanation is grounded in already-published, server-owned events.
    from app.services import get_request_for_actor, request_view
    view = request_view(session, get_request_for_actor(session, request_id, actor_id))
    message = view.events[-1].public_message if view.events else "已读取服务端状态"
    return AgentRunRead(request_id=request_id, status=observation["status"], matching_issue=observation["matching_issue"], step_count=1,
        provider=router.active, fallback_active=router.fallback_active, message=message, action_committed=False)

"""Predictable, network-free demonstration provider."""

import re
from datetime import datetime

from app.agent_schemas import ActionProposal, ParsedFields, Urgency, ambiguous_deadline_text


class MockLLMProvider:
    name = "mock"
    configured = True

    async def parse(self, text: str, now: datetime, known: dict) -> ParsedFields:
        item = known.get("item_type")
        for word, code in (("科学计算器", "scientific_calculator"), ("计算器", "scientific_calculator"), ("充电器", "charger"), ("转接头", "adapter"), ("文具", "stationery"), ("雨伞", "umbrella")):
            if word in text:
                item = code
                break
        location_match = re.search(r"(?:在|地点[:：]?\s*)(VA|PQ|Library)(?![A-Za-z])", text, re.I)
        minutes_match = None if ambiguous_deadline_text(text) else re.search(r"(\d{1,4})\s*分钟后", text)
        return ParsedFields(
            item_type=item,
            location=location_match.group(1).upper() if location_match else known.get("location"),
            deadline_in_minutes=int(minutes_match.group(1)) if minutes_match else None,
            deadline_at=None if ambiguous_deadline_text(text) else known.get("deadline") if not minutes_match else None,
            urgency=Urgency.high if ("考试" in text or (minutes_match and int(minutes_match.group(1)) <= 20)) else known.get("urgency"),
        )

    async def choose(self, observation: dict, allowed: list[str]) -> ActionProposal:
        name = "send_help_offer" if observation.get("status") == "draft" and "send_help_offer" in allowed else "wait_for_response" if observation.get("status") == "awaiting_response" else "finish"
        return ActionProposal(name=name, arguments={"request_id": observation["request_id"]})

    async def close(self) -> None:
        return None

"""Predictable, network-free demonstration provider."""

import re
from datetime import datetime

from app.agent_schemas import ActionProposal, ParsedFields, Urgency, ambiguous_deadline_text, location_from_text
from app.schemas import ItemType


KNOWN_ITEMS = (
    (("科学计算器", "科學計算器", "计算器", "計算器", "scientific calculator"), "scientific_calculator", "科学计算器"),
    (("充电器", "充電器", "charger"), "charger", "充电器"),
    (("转接头", "轉接頭", "adapter"), "adapter", "转接头"),
    (("文具",), "stationery", "文具"),
    (("雨伞", "雨傘", "umbrella"), "umbrella", "雨伞"),
)


def _request_category(text: str, known: dict) -> str:
    if re.search(r"搬运|搬運|帮我|幫我|帮忙|幫忙|代取|陪同|服务|服務", text, re.I):
        return "service"
    if re.search(r"借|borrow", text, re.I):
        return "borrow"
    return known.get("category") or "borrow"


def _need_summary(text: str, category: str, item: str, brand: str | None, model: str | None, known: dict) -> str | None:
    if category == "service" and re.search(r"搬运|搬運", text) and re.search(r"实验器材|實驗器材", text):
        return ("有偿" if "有偿" in text or "有償" in text else "") + "帮忙搬运实验器材"
    if category == "borrow" and item != ItemType.other.value:
        labels = {code: label for _, code, label in KNOWN_ITEMS}
        return " ".join(part for part in (brand, model, labels[item]) if part)
    stated_need = re.search(r"(?:想?借|需要|求助|帮我|幫我|帮忙|幫忙|搬运|搬運|代取|陪同|borrow|need)\s*([^，,。；;!?！？]{1,100})", text, re.I)
    if stated_need and stated_need.group(1).strip():
        summary = re.sub(r"\d{1,4}\s*分钟(?:之)?后", "", text)
        summary = re.sub(r"(?:在|於|于)\s*[^，,。；;]{1,30}[，,]", "", summary).strip(" ，,。；;")
        return summary[:200] or known.get("need_summary")
    return known.get("need_summary")


def _explicit_exact_only(text: str) -> bool:
    return bool(re.search(r"只(?:接受|要)|不能替代|不可替代|不要替代|不接受替代|exact\s+only", text, re.I))


class MockLLMProvider:
    name = "mock"
    configured = True

    async def parse(self, text: str, now: datetime, known: dict) -> ParsedFields:
        category = _request_category(text, known)
        item = known.get("item_type") or ItemType.other.value
        if category == "service":
            item = ItemType.other.value
        else:
            for words, code, _ in KNOWN_ITEMS:
                if any(word.casefold() in text.casefold() for word in words):
                    item = code
                    break
        location = location_from_text(text)
        minutes_match = None if ambiguous_deadline_text(text) else re.search(r"(\d{1,4})\s*分钟(?:之)?后", text)
        brand = None if category == "service" else "Casio" if re.search(r"(?<![A-Za-z])Casio(?![A-Za-z])|卡西欧|卡西歐", text, re.I) else known.get("preferred_brand")
        model_match = re.search(r"(?<![A-Za-z0-9])fx[-\s]?[A-Za-z0-9-]{2,30}(?![A-Za-z0-9])", text, re.I)
        model = None if category == "service" else model_match.group(0) if model_match else known.get("preferred_model")
        exact_only = category == "borrow" and (_explicit_exact_only(text) or known.get("substitution_policy") == "exact_only")
        return ParsedFields(
            category=category,
            need_summary=_need_summary(text, category, item, brand, model, known),
            item_type=item,
            preferred_brand=brand,
            preferred_model=model,
            substitution_policy="exact_only" if exact_only else None,
            location=location if location is not None else known.get("location"),
            deadline_in_minutes=int(minutes_match.group(1)) if minutes_match else None,
            deadline_at=None if ambiguous_deadline_text(text) else known.get("deadline") if not minutes_match else None,
            urgency=Urgency.high if ("考试" in text or (minutes_match and int(minutes_match.group(1)) <= 20)) else known.get("urgency"),
        )

    async def choose(self, observation: dict, allowed: list[str]) -> ActionProposal:
        name = "publish_request" if "publish_request" in allowed else "wait_for_response" if observation.get("status") == "awaiting_response" else "finish"
        return ActionProposal(name=name, arguments={"request_id": observation["request_id"]})

    async def close(self) -> None:
        return None

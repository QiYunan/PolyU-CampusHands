"""OpenAI-compatible Chat Completions adapter shared by DeepSeek and Ollama."""

import json
import re
from datetime import datetime

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from app.agent_schemas import ActionProposal, ParsedFields, ambiguous_deadline_text, location_from_text, preference_is_grounded
from app.providers.base import ProviderError
from app.schemas import ItemType


TOOL_NAMES = ("ask_clarification", "create_help_request", "search_helpers", "publish_request", "observe_request", "wait_for_response", "finish")


def tool_schemas(allowed: list[str]) -> list[dict]:
    schemas = []
    for name in allowed:
        if name not in TOOL_NAMES:
            raise ValueError("Unregistered tool")
        field = "draft_id" if name in {"ask_clarification", "create_help_request"} else "request_id"
        properties = {field: {"type": "integer", "minimum": 1}}
        required = [field]
        if name == "ask_clarification":
            properties["missing_fields"] = {"type": "array", "items": {"type": "string", "enum": ["need_summary", "location", "deadline"]}}
            required.append("missing_fields")
        schemas.append({"type": "function", "function": {"name": name, "description": "Propose a bounded CampusHands action; server validates and executes it", "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}})
    return schemas


class CompatibleProvider:
    def __init__(self, name: str, base_url: str, api_key: str | None, model: str, timeout: float, deepseek: bool = False):
        self.name = name
        self.model = model
        self.deepseek = deepseek
        self.configured = bool(api_key)
        # Local Ollama must not inherit a system proxy, which can turn loopback calls into 502s.
        local_http_client = httpx.AsyncClient(trust_env=False, timeout=timeout) if name == "ollama" else None
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key or "unconfigured", timeout=timeout, max_retries=0,
                                  **({"http_client": local_http_client} if local_http_client else {}))

    async def _complete(self, **kwargs):
        if not self.configured:
            raise ProviderError("unconfigured", retryable=False)
        if self.deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        elif self.name == "ollama":
            kwargs["reasoning_effort"] = "none"
        try:
            return await self.client.chat.completions.create(model=self.model, stream=False, **kwargs)
        except (APIConnectionError, APITimeoutError):
            raise ProviderError("connection_or_timeout") from None
        except APIStatusError as error:
            retryable = error.status_code == 429 or error.status_code >= 500
            raise ProviderError("rate_limited" if error.status_code == 429 else "server_error" if error.status_code >= 500 else "provider_rejected", retryable=retryable) from None

    async def parse(self, text: str, now: datetime, known: dict) -> ParsedFields:
        response_format = {"type": "json_object"} if self.deepseek else {"type": "json_schema", "json_schema": {"name": "parsed_campus_help_request", "schema": ParsedFields.model_json_schema()}}
        instruction = (
            "Return JSON only. Extract a campus help request whose category is borrow or service. "
            "Return a concise, faithful need_summary. Use item_type codes scientific_calculator, charger, adapter, "
            "stationery, umbrella, or other; use other for an unknown borrowed object and for every service. "
            "A request to help move laboratory equipment is service, never scientific_calculator. "
            "For service, preferred_brand and preferred_model must be null. For borrow, extract them only when "
            "explicitly supplied. Set substitution_policy to exact_only only when the requester explicitly says only "
            "that exact option is acceptable or that substitutes are not allowed; otherwise use null. Never choose a Helper. "
            "For relative deadlines return deadline_in_minutes; for explicit absolute deadlines use deadline_at with timezone. "
            "Return location and urgency normal or high; high for an imminent exam or need within 20 minutes. "
            "Never invent a missing required fact."
        )
        if self.name == "ollama":
            instruction += " PolyU building codes and common names include VA, PQ, Z栋, Block Z, Library and 图书馆. A numeric Chinese phrase N分钟后 or N分钟之后 MUST set deadline_in_minutes to N and deadline_at to null. Example: 30分钟之后 means deadline_in_minutes 30."
        response = await self._complete(
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps({"text": text, "now_utc": now.isoformat(), "known_fields": known}, ensure_ascii=False, default=str)},
            ],
            response_format=response_format,
        )
        try:
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("empty model result")
            parsed = ParsedFields.model_validate_json(content)
            service_intent = bool(re.search(r"搬运|搬運|帮我|幫我|帮忙|幫忙|代取|陪同|服务|服務", text, re.I))
            if service_intent or (known.get("category") == "service" and not re.search(r"借|borrow", text, re.I)):
                service_summary = parsed.need_summary
                if re.search(r"搬运|搬運", text) and re.search(r"实验器材|實驗器材", text):
                    service_summary = ("有偿" if "有偿" in text or "有償" in text else "") + "帮忙搬运实验器材"
                parsed = ParsedFields.model_validate({**parsed.model_dump(), "category": "service", "item_type": ItemType.other,
                                                       "need_summary": service_summary,
                                                       "preferred_brand": None, "preferred_model": None,
                                                       "substitution_policy": None})
            if not preference_is_grounded(parsed.preferred_brand, text, known.get("preferred_brand")) or not preference_is_grounded(parsed.preferred_model, text, known.get("preferred_model")):
                raise ValueError("ungrounded preference")
            explicit_exact = bool(re.search(r"只(?:接受|要)|不能替代|不可替代|不要替代|不接受替代|exact\s+only", text, re.I))
            grounded_exact = parsed.category == "borrow" and (explicit_exact or known.get("substitution_policy") == "exact_only")
            parsed = ParsedFields.model_validate({**parsed.model_dump(),
                                                   "item_type": parsed.item_type or ItemType.other,
                                                   "substitution_policy": "exact_only" if grounded_exact else None})
            stated_location = location_from_text(text)
            if stated_location is not None:
                parsed = ParsedFields.model_validate({**parsed.model_dump(), "location": stated_location})
            elif parsed.location and parsed.location != known.get("location"):
                parsed = ParsedFields.model_validate({**parsed.model_dump(), "location": None})
            # Reconcile one explicit numeric phrase deterministically, then validate again.
            if ambiguous_deadline_text(text):
                parsed = ParsedFields.model_validate({**parsed.model_dump(), "deadline_in_minutes": None, "deadline_at": None})
            else:
                relative = re.findall(r"(\d{1,4})\s*分钟(?:之)?后", text)
                if len(relative) == 1:
                    parsed = ParsedFields.model_validate({**parsed.model_dump(), "deadline_in_minutes": int(relative[0]), "deadline_at": None})
            return parsed
        except (IndexError, ValueError, ValidationError):
            raise ProviderError("invalid_output") from None

    async def choose(self, observation: dict, allowed: list[str]) -> ActionProposal:
        response = await self._complete(
            messages=[
                {"role": "system", "content": "Choose exactly one supplied high-level tool. Tool arguments may contain only the observed request_id. publish_request asks the deterministic service to validate state and publish to the Helper board; it never selects a Helper or creates a pending invitation. The model must never specify a Helper, Item, invitation text, inventory, position, candidate count or score. search_helpers performs at most one read-only service precheck and returns only a safe request-level issue code, never candidate details. For an awaiting_response request use wait_for_response. Do not assert that a request is matched or completed. If native tool calling is unavailable, return JSON with name and arguments."},
                {"role": "user", "content": json.dumps({"observation": observation, "allowed_actions": allowed}, ensure_ascii=False)},
            ],
            tools=tool_schemas(allowed),
            tool_choice="auto",
        )
        try:
            message = response.choices[0].message
            if message.tool_calls:
                if len(message.tool_calls) != 1:
                    raise ValueError("one tool expected")
                call = message.tool_calls[0]
                result = ActionProposal(name=call.function.name, arguments=json.loads(call.function.arguments))
            else:
                result = ActionProposal.model_validate_json(message.content or "")
            if result.name not in allowed:
                raise ValueError("tool not allowed")
            return result
        except (IndexError, ValueError, ValidationError, TypeError):
            raise ProviderError("invalid_action") from None

    async def close(self) -> None:
        await self.client.close()

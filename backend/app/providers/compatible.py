"""OpenAI-compatible Chat Completions adapter shared by DeepSeek and Ollama."""

import json
import re
from datetime import datetime

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from app.agent_schemas import ActionProposal, ParsedFields, ambiguous_deadline_text
from app.providers.base import ProviderError


TOOL_NAMES = ("ask_clarification", "create_help_request", "search_helpers", "send_help_offer", "observe_request", "wait_for_response", "finish")


def tool_schemas(allowed: list[str]) -> list[dict]:
    schemas = []
    for name in allowed:
        if name not in TOOL_NAMES:
            raise ValueError("Unregistered tool")
        field = "draft_id" if name in {"ask_clarification", "create_help_request"} else "request_id"
        properties = {field: {"type": "integer", "minimum": 1}}
        required = [field]
        if name == "send_help_offer":
            properties["message"] = {"type": "string", "maxLength": 300}
        if name == "ask_clarification":
            properties["missing_fields"] = {"type": "array", "items": {"type": "string", "enum": ["item_type", "location", "deadline"]}}
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
        response_format = {"type": "json_object"} if self.deepseek else {"type": "json_schema", "json_schema": {"name": "parsed_borrow_request", "schema": ParsedFields.model_json_schema()}}
        instruction = "Return JSON only. Extract a borrow request. Use item_type codes scientific_calculator, charger, adapter, stationery, umbrella. Use null for absent facts. For relative deadlines return deadline_in_minutes; for explicit absolute deadlines use deadline_at with timezone. Return category borrow, location, urgency normal or high; high for an imminent exam or need within 20 minutes. Never invent a missing field."
        if self.name == "ollama":
            instruction += " VA, PQ and Library are campus location codes: 在VA考试 means location VA. A numeric Chinese phrase N分钟后 MUST set deadline_in_minutes to N and deadline_at to null. Example: 20分钟后 means deadline_in_minutes 20, not a missing deadline."
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
            # Small local models may omit an explicit numeric relative deadline.
            # Normalize only one unambiguous phrase, then validate the result again.
            if ambiguous_deadline_text(text):
                parsed = ParsedFields.model_validate({**parsed.model_dump(), "deadline_in_minutes": None, "deadline_at": None})
            elif self.name == "ollama":
                relative = re.findall(r"(\d{1,4})\s*分钟后", text)
                if len(relative) == 1:
                    parsed = ParsedFields.model_validate({**parsed.model_dump(), "deadline_in_minutes": int(relative[0]), "deadline_at": None})
            return parsed
        except (IndexError, ValueError, ValidationError):
            raise ProviderError("invalid_output") from None

    async def choose(self, observation: dict, allowed: list[str]) -> ActionProposal:
        response = await self._complete(
            messages=[
                {"role": "system", "content": "Choose exactly one supplied tool. Tool arguments must identify only the observed request. If a draft already has candidate_count, use send_help_offer to ask the deterministic service to create the next Offer; search_helpers only refreshes the same observation and should not be repeated. When the request is awaiting_response, use wait_for_response. For send_help_offer, write an optional short Chinese invitation based only on observed item_type and location, without names or claims of acceptance. Do not invent users, offers, status or completion. If native tool calling is unavailable, return JSON with name and arguments."},
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

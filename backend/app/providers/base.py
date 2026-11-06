"""Provider protocol and sanitized errors."""

from datetime import datetime
from typing import Protocol

from app.agent_schemas import ActionProposal, ParsedFields


class ProviderError(Exception):
    def __init__(self, code: str, retryable: bool = True):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class LLMUnavailable(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    configured: bool

    async def parse(self, text: str, now: datetime, known: dict) -> ParsedFields: ...
    async def choose(self, observation: dict, allowed: list[str]) -> ActionProposal: ...
    async def close(self) -> None: ...

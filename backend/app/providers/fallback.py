"""Retry model-only calls; never replay database actions."""

from datetime import datetime

from app.providers.base import LLMProvider, LLMUnavailable, ProviderError


class ProviderRouter:
    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None = None):
        self.primary = primary
        self.fallback = fallback
        self.active: str | None = None
        self.fallback_active = False
        self.states = {primary.name: "unknown" if primary.configured else "unconfigured"}
        if fallback is not None:
            self.states[fallback.name] = "unknown" if fallback.configured else "unconfigured"

    async def _call(self, method: str, *args):
        self.active = None
        self.fallback_active = False
        providers = [(self.primary, 2)]
        if self.fallback is not None and self.fallback.name != self.primary.name:
            providers.append((self.fallback, 1))
        for provider, attempts in providers:
            if not provider.configured:
                self.states[provider.name] = "unconfigured"
                continue
            for attempt in range(attempts):
                try:
                    result = await getattr(provider, method)(*args)
                    self.states[provider.name] = "available"
                    self.active = provider.name
                    self.fallback_active = provider is self.fallback
                    return result
                except ProviderError as error:
                    self.states[provider.name] = "unavailable"
                    if not error.retryable or attempt + 1 >= attempts:
                        break
        raise LLMUnavailable("Model providers are unavailable; retry later")

    async def parse(self, text: str, now: datetime, known: dict):
        return await self._call("parse", text, now, known)

    async def choose(self, observation: dict, allowed: list[str]):
        return await self._call("choose", observation, allowed)

    def status(self) -> dict:
        return {"primary": self.primary.name, "fallback": self.fallback.name if self.fallback else None, "active": self.active, "primary_status": self.states[self.primary.name], "fallback_status": self.states.get(self.fallback.name) if self.fallback else None, "fallback_active": self.fallback_active}

    async def close(self) -> None:
        await self.primary.close()
        if self.fallback is not None and self.fallback is not self.primary:
            await self.fallback.close()

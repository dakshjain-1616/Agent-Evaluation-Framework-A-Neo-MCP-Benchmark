"""LLM provider implementations — wraps Anthropic SDK (and others) behind LLMProvider interface."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from neo_mcp.core.interfaces import LLMProvider


class AnthropicLLMProvider(LLMProvider):
    """LLMProvider implementation using the Anthropic Python SDK.

    Uses claude-opus-4-8 by default for planning/reasoning tasks.
    """

    def __init__(
        self,
        model_id: str = "claude-opus-4-8",
        api_key: Optional[str] = None,
        max_retries: int = 3,
    ) -> None:
        self._model_id = model_id
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._max_retries = max_retries
        self._client: Any = None

    def _get_client(self):
        """Lazy-init the anthropic client."""
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    @property
    def model_id(self) -> str:
        return self._model_id

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Generate a response from Claude."""
        client = self._get_client()

        import anthropic

        try:
            response = client.messages.create(
                model=self._model_id,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.content[0].text
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Anthropic API error: {e}") from e
        except Exception as e:
            raise RuntimeError(f"LLM generation failed: {e}") from e


class FakeLLMProvider(LLMProvider):
    """Fake LLM provider for testing — returns predetermined responses."""

    def __init__(
        self,
        responses: Optional[Dict[str, str]] = None,
        default_response: str = "{}",
    ) -> None:
        self._responses = responses or {}
        self._default = default_response
        self.call_history: List[Dict[str, Any]] = []

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        self.call_history.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        # Check for exact match first
        if user_prompt in self._responses:
            return self._responses[user_prompt]
        return self._default
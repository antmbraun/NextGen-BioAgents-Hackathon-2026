from __future__ import annotations

import json
import re
from typing import Any

import httpx

from fda_510k.config import (
    DEFAULT_NEBIUS_BASE_URL,
    get_nebius_api_key,
    get_nebius_base_url,
    get_nebius_model,
)


class NebiusClient:
    """OpenAI-compatible client for Nebius Token Factory."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or get_nebius_api_key()
        self.model = model or get_nebius_model()
        self.base_url = (base_url or get_nebius_base_url() or DEFAULT_NEBIUS_BASE_URL).rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate(self, prompt: str, *, system: str | None = None, temperature: float = 0.1) -> str:
        if not self.is_available():
            raise RuntimeError(
                "Nebius API key not configured. Set NEBIUS_API_KEY in .env or Streamlit secrets."
            )

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Nebius returned no choices: {data}")

        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if not content:
            raise RuntimeError(f"Nebius returned empty content: {data}")

        return content

    @staticmethod
    def _extract_json(text: str) -> Any:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            return json.loads(match.group(1).strip())
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")

    def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        retries: int = 2,
    ) -> Any:
        system_prompt = (system or "") + "\nRespond with valid JSON only. No markdown."
        last_error: Exception | None = None
        for _ in range(retries + 1):
            try:
                raw = self.generate(prompt, system=system_prompt.strip(), temperature=0.0)
                return self._extract_json(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
        raise ValueError(f"Failed to get valid JSON after {retries + 1} attempts") from last_error

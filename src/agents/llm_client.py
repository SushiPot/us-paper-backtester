from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class LLMResponse:
    """LLM ?????"""

    model: str
    content: str


class OpenRouterClient:
    """OpenRouter ? OpenAI-compatible Chat Completions ????"""

    base_url = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.model = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip()
        self.site_url = os.getenv("OPENROUTER_SITE_URL", "http://127.0.0.1:5000").strip()
        self.app_name = os.getenv("OPENROUTER_APP_NAME", "us-paper-backtester").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        if not self.configured:
            raise RuntimeError("OPENROUTER_API_KEY ?????? LLM Agent")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.app_name,
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1200,
        }
        response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        routed_model = str(data.get("model", self.model))
        return LLMResponse(model=routed_model, content=str(content))

import asyncio
import json
from typing import Protocol

import httpx

from app.ai.prompts import SYSTEM_PROMPT, draft_spec_json_schema
from app.config import Settings


class ProviderError(RuntimeError):
    """Safe provider error whose message never includes credentials."""


class ProviderTimeoutError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class LLMProvider(Protocol):
    last_response_id: str | None

    async def parse_modeling_request(self, text: str) -> dict[str, object]: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider_name = provider_name.strip().casefold()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self.last_response_id: str | None = None

    @classmethod
    def from_settings(
        cls, settings: Settings, *, client: httpx.AsyncClient | None = None
    ) -> "OpenAICompatibleProvider":
        if not settings.ai_is_configured:
            raise ValueError("language-model provider is not configured")
        assert settings.llm_base_url is not None
        assert settings.llm_api_key is not None
        assert settings.llm_model is not None
        return cls(
            provider_name=settings.llm_provider,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            client=client,
        )

    async def parse_modeling_request(self, text: str) -> dict[str, object]:
        schema = draft_spec_json_schema()
        is_deepseek = self.provider_name == "deepseek" or "deepseek.com" in self.base_url
        system_prompt = SYSTEM_PROMPT
        if is_deepseek:
            system_prompt += "\n必须只输出一个JSON对象。JSON Schema如下：\n"
            system_prompt += json.dumps(schema, ensure_ascii=False)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "response_format": (
                {"type": "json_object"}
                if is_deepseek
                else {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "hysys_modeling_draft",
                        # Composition and stoichiometry use dynamic component keys;
                        # strict Structured Outputs cannot represent those maps.
                        # Pydantic still strictly validates the returned payload.
                        "strict": False,
                        "schema": schema,
                    },
                }
            ),
        }
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=self.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError("language-model request timed out") from exc
            except httpx.HTTPError as exc:
                raise ProviderError("language-model request failed") from exc

            if (
                response.status_code == 429 or response.status_code >= 500
            ) and attempt < self.max_retries:
                await asyncio.sleep(0)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProviderResponseError(
                    f"language-model request failed with status {response.status_code}"
                ) from exc

            try:
                envelope = response.json()
                self.last_response_id = envelope.get("id")
                content = envelope["choices"][0]["message"]["content"]
                payload = json.loads(content)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise ProviderResponseError("language-model response was not valid JSON") from exc
            if not isinstance(payload, dict):
                raise ProviderResponseError("language-model response must be a JSON object")
            return payload

        raise ProviderResponseError("language-model request exhausted retries")

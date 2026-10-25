import json
import logging

import httpx
import pytest

from app.ai.provider import OpenAICompatibleProvider, ProviderTimeoutError
from app.config import Settings


def _settings(**overrides):
    values = {
        "llm_base_url": "https://llm.example.test/v1",
        "llm_api_key": "super-secret-key",
        "llm_model": "engineering-model",
        "llm_max_retries": 2,
        "llm_timeout_seconds": 1,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_provider_uses_configured_endpoint_model_and_schema():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp-123",
                "choices": [{"message": {"content": json.dumps({"title": "test"})}}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider.from_settings(_settings(), client=client)

    payload = await provider.parse_modeling_request("模拟反应")

    assert payload == {"title": "test"}
    assert provider.last_response_id == "resp-123"
    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer super-secret-key"
    assert captured["body"]["model"] == "engineering-model"
    assert captured["body"]["response_format"]["type"] == "json_schema"
    await client.aclose()


@pytest.mark.asyncio
async def test_deepseek_provider_uses_json_object_response_format():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "deepseek-response",
                "choices": [{"message": {"content": '{"title":"test"}'}}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider.from_settings(
        _settings(
            llm_provider="deepseek",
            llm_base_url="https://api.deepseek.com",
            llm_model="deepseek-flash",
        ),
        client=client,
    )

    assert await provider.parse_modeling_request("模拟反应") == {"title": "test"}
    assert captured["body"]["response_format"] == {"type": "json_object"}
    prompt = captured["body"]["messages"][0]["content"]
    assert "分组分流量" in prompt
    assert "所有反应物和产物" in prompt
    assert "用户原文明确出现" in prompt
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_retries_transient_responses():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={"id": "ok", "choices": [{"message": {"content": '{"title":"ok"}'}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider.from_settings(_settings(), client=client)

    assert await provider.parse_modeling_request("retry") == {"title": "ok"}
    assert attempts == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_timeout_is_typed_and_secret_is_not_logged(caplog):
    def handler(request):
        raise httpx.ReadTimeout("request with super-secret-key timed out", request=request)

    caplog.set_level(logging.DEBUG)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider.from_settings(_settings(), client=client)

    with pytest.raises(ProviderTimeoutError, match="timed out"):
        await provider.parse_modeling_request("slow")

    assert "super-secret-key" not in caplog.text
    await client.aclose()

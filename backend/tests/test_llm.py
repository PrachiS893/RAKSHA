"""Tests for Groq LLM service integration, structured output validation, and security."""

from typing import Any, Optional
import httpx
from pydantic import BaseModel
import pytest
from app.config import settings
from app.services.llm import generate_json


class SampleTestSchema(BaseModel):
    answer: str


def make_mock_response(
    status_code: int, json_data: Any = None, text: Optional[str] = None
) -> httpx.Response:
    """Helper creating an httpx.Response for tests."""
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    if text is not None:
        return httpx.Response(status_code=status_code, text=text, request=request)
    return httpx.Response(
        status_code=status_code,
        json=json_data if json_data is not None else {},
        request=request,
    )


def test_valid_json_response_parses_into_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "gsk_mock_valid_key")

    def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return make_mock_response(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"answer": "success_test"}',
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    result = generate_json(prompt="test prompt", schema=SampleTestSchema)
    assert result is not None
    assert isinstance(result, SampleTestSchema)
    assert result.answer == "success_test"


def test_code_fenced_response_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "gsk_mock_valid_key")

    fenced_content = '```json\n{"answer": "fenced_content_test"}\n```'

    def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return make_mock_response(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": fenced_content,
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    result = generate_json(prompt="test prompt", schema=SampleTestSchema)
    assert result is not None
    assert result.answer == "fenced_content_test"


def test_invalid_json_retries_once_then_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "gsk_mock_valid_key")

    call_count = 0

    def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return make_mock_response(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "{malformed json",
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    result = generate_json(prompt="test prompt", schema=SampleTestSchema)
    assert result is None
    # Must retry once before returning None (1 initial call + 1 retry = 2 total calls)
    assert call_count == 2


def test_http_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "gsk_mock_valid_key")

    def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return make_mock_response(status_code=500, text="Internal Server Error")

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    result = generate_json(prompt="test prompt", schema=SampleTestSchema)
    assert result is None


def test_400_response_format_triggers_json_object_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "gsk_mock_valid_key")

    request_formats: list[dict[str, Any]] = []

    def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        json_body = kwargs.get("json", {})
        request_formats.append(json_body.get("response_format", {}))

        # First request attempts json_schema and gets rejected with 400
        if len(request_formats) == 1:
            return make_mock_response(
                status_code=400,
                text='{"error": {"message": "The model does not support response_format json_schema"}}',
            )

        # Fallback request uses json_object and succeeds
        return make_mock_response(
            status_code=200,
            json_data={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"answer": "fallback_success"}',
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    result = generate_json(prompt="test prompt", schema=SampleTestSchema)
    assert result is not None
    assert result.answer == "fallback_success"
    assert len(request_formats) == 2
    assert request_formats[0].get("type") == "json_schema"
    assert request_formats[1].get("type") == "json_object"


def test_empty_key_returns_none_without_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", "")

    called = False

    def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal called
        called = True
        return make_mock_response(status_code=200)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    result = generate_json(prompt="test prompt", schema=SampleTestSchema)
    assert result is None
    assert not called


def test_fake_key_never_appears_in_logs_or_detail(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_key = "FAKE_GROQ_SECRET_KEY_ABC123456789"
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY", secret_key)

    # 1. Trigger HTTP error
    def mock_post_err(*args: Any, **kwargs: Any) -> httpx.Response:
        return make_mock_response(status_code=401, text="Unauthorized: invalid api key")

    monkeypatch.setattr(httpx.Client, "post", mock_post_err)

    with caplog.at_level("DEBUG"):
        generate_json(prompt="test", schema=SampleTestSchema)

    # 2. Trigger connection timeout exception
    def mock_post_exc(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out to https://api.groq.com")

    monkeypatch.setattr(httpx.Client, "post", mock_post_exc)

    with caplog.at_level("DEBUG"):
        generate_json(prompt="test", schema=SampleTestSchema)

    # Assert secret key was never written to any captured log message
    for record in caplog.records:
        assert secret_key not in record.message

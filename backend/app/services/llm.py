"""LLM service providing structured JSON responses via Groq's OpenAI-compatible API."""

import json
import logging
from typing import Optional, TypeVar
import httpx
from pydantic import BaseModel, ValidationError
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


def _clean_content(raw_content: str) -> str:
    """Strip markdown code block fences and surrounding whitespace from raw content."""
    text = raw_content.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1 :]
        else:
            text = text.lstrip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _call_groq_api(
    client: httpx.Client,
    api_key: str,
    prompt: str,
    schema: type[T],
    system: Optional[str],
) -> Optional[str]:
    """Execute chat completion request to Groq, handling json_schema and json_object fallback."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
            },
        },
    }

    resp = client.post(
        GROQ_CHAT_COMPLETIONS_URL,
        json=payload,
        headers=headers,
    )

    # If Groq rejects json_schema for the configured model, fall back once to json_object
    if resp.status_code == 400:
        err_lower = resp.text.lower()
        if "response_format" in err_lower or "schema" in err_lower:
            field_names = list(schema.model_fields.keys())
            fallback_prompt = (
                f"{prompt}\nReturn a JSON object with fields: {', '.join(field_names)}."
            )
            fallback_messages = []
            if system:
                fallback_messages.append({"role": "system", "content": system})
            fallback_messages.append({"role": "user", "content": fallback_prompt})

            fallback_payload = {
                "model": settings.LLM_MODEL,
                "messages": fallback_messages,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
            resp = client.post(
                GROQ_CHAT_COMPLETIONS_URL,
                json=fallback_payload,
                headers=headers,
            )

    if resp.status_code != 200:
        logger.warning("generate_json received HTTP %d", resp.status_code)
        return None

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        logger.warning("generate_json response missing choices")
        return None

    content = choices[0].get("message", {}).get("content")
    return content


def generate_json(
    prompt: str, schema: type[T], system: Optional[str] = None
) -> Optional[T]:
    """Generate structured JSON from Groq validated against a Pydantic schema.

    Returns None if:
      - LLM_ENABLED is false
      - LLM_API_KEY is unset or empty
      - Network / API call errors or times out (LLM_TIMEOUT_SECONDS)
      - Response fails schema validation after ONE retry

    SECURITY:
      Never logs or stores the API key, Authorization header, or raw exception text.
      On failure, logs only the HTTP status code or exception class name. Never raises.
    """
    if not settings.LLM_ENABLED:
        logger.debug("LLM_ENABLED is False; returning None")
        return None

    api_key = settings.LLM_API_KEY.strip() if settings.LLM_API_KEY else ""
    if not api_key:
        logger.debug("No LLM_API_KEY configured; returning None")
        return None

    max_validation_attempts = 2  # Initial call + 1 retry on Pydantic validation failure

    with httpx.Client(timeout=float(settings.LLM_TIMEOUT_SECONDS)) as client:
        for attempt in range(1, max_validation_attempts + 1):
            try:
                content = _call_groq_api(
                    client=client,
                    api_key=api_key,
                    prompt=prompt,
                    schema=schema,
                    system=system,
                )
                if content is None:
                    # HTTP error or empty response: return None directly without retrying
                    return None

                clean = _clean_content(content)
                if not clean:
                    raise ValueError("Empty content returned from LLM")

                parsed = json.loads(clean)
                return schema.model_validate(parsed)

            except (json.JSONDecodeError, ValidationError, ValueError, TypeError, KeyError) as exc:
                logger.warning(
                    "generate_json validation attempt %d/%d failed: %s",
                    attempt,
                    max_validation_attempts,
                    exc.__class__.__name__,
                )
                if attempt == max_validation_attempts:
                    return None
            except Exception as exc:
                logger.warning(
                    "generate_json failed with error: %s",
                    exc.__class__.__name__,
                )
                return None

    return None

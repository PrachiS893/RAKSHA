"""LLM service providing structured JSON responses via the google-genai SDK."""

import logging
from typing import Optional, TypeVar
from google import genai
from google.genai import types
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def generate_json(
    prompt: str, schema: type[T], system: Optional[str] = None
) -> Optional[T]:
    """Generate structured JSON from Gemini validated against a Pydantic schema.

    Returns None if:
      - LLM_API_KEY is unset or empty
      - Network / API call errors or times out
      - Response fails schema validation (retried once before returning None)

    Never logs or exposes the API key. Designed for simple monkeypatching in tests.
    """
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        logger.debug("No LLM_API_KEY set; falling back to template text")
        return None

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        system_instruction=system,
    )

    max_attempts = 2  # Initial call + 1 retry on validation / API failure
    for attempt in range(1, max_attempts + 1):
        try:
            client = genai.Client(api_key=settings.LLM_API_KEY)
            response = client.models.generate_content(
                model=settings.LLM_MODEL,
                contents=prompt,
                config=config,
            )
            raw_text = response.text
            if not raw_text:
                raise ValueError("Empty response text returned from Gemini API")

            return schema.model_validate_json(raw_text)
        except Exception as exc:
            logger.warning(
                "generate_json attempt %d/%d failed: %s", attempt, max_attempts, exc
            )

    return None

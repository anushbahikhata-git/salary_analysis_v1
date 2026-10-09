import os
import requests

from pathlib import Path
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT
# =========================================================

BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / ".env")


OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY"
)

OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL"
)

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)


# =========================================================
# OPENROUTER CALL
# =========================================================

def call_openrouter(
    system_prompt: str,
    user_prompt: str
) -> str:

    # Read at call time (not only at import time) so the key is
    # found regardless of import order vs .env loading.
    api_key = (
        os.getenv("OPENROUTER_API_KEY")
        or OPENROUTER_API_KEY
    )

    model = (
        os.getenv("OPENROUTER_MODEL")
        or OPENROUTER_MODEL
    )

    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is missing"
        )

    if not model:
        raise ValueError(
            "OPENROUTER_MODEL is missing"
        )

    headers = {
        "Authorization": (
            f"Bearer {api_key}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,

        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],

        "temperature": 0,

        # Give the model enough room to analyze
        # long CRIF / CIBIL / Experian reports.
        "max_tokens": 8000,

        # Keep reasoning controlled.
        "reasoning": {
            "effort": "low"
        },

        # Force JSON output.
        "response_format": {
            "type": "json_object"
        }
    }

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=180,
    )

    response.raise_for_status()

    data = response.json()

    # =====================================================
    # CHECK OPENROUTER RESPONSE
    # =====================================================

    if not data.get("choices"):
        raise ValueError(
            f"OpenRouter returned no choices: {data}"
        )

    choice = data["choices"][0]

    message = choice.get(
        "message",
        {}
    )

    content = message.get(
        "content"
    )

    finish_reason = choice.get(
        "finish_reason"
    )

    # =====================================================
    # HANDLE PREMATURE / LENGTH RESPONSE
    # =====================================================

    if not content:

        if finish_reason == "length":

            raise ValueError(
                "OpenRouter model reached the output "
                "token limit before producing JSON. "
                "Increase max_tokens or reduce reasoning."
            )

        raise ValueError(
            f"OpenRouter returned empty content: {data}"
        )

    return content
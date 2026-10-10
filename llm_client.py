"""
llm_client.py
Single reusable function for calling the Groq API.
Every mode (Excel/SQL/Python) goes through call_llm() so retry/timeout
logic lives in exactly one place.
"""

import os
import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"  # confirmed available via /v1/models on this account (Sep 2026)
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 2


class LLMResult:
    def __init__(self, success, text=None, error=None):
        self.success = success
        self.text = text
        self.error = error


def get_api_key():
    return os.environ.get("GROQ_API_KEY", "")


def call_llm(system_prompt: str, user_prompt: str) -> LLMResult:
    api_key = get_api_key()
    if not api_key:
        return LLMResult(False, error="No Groq API key found. Add GROQ_API_KEY to your .env or Streamlit secrets.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,  # low temperature — we want correctness, not creativity
        "max_tokens": 1024,
    }

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                GROQ_API_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code == 200:
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                return LLMResult(True, text=text)
            elif response.status_code == 429:
                last_error = "Rate limit hit on the free tier. Please wait a moment and try again."
                continue  # retry
            else:
                last_error = f"API error ({response.status_code}): {response.text[:200]}"
        except requests.exceptions.Timeout:
            last_error = "Request timed out. The API may be slow right now."
        except requests.exceptions.RequestException as e:
            last_error = f"Network error: {str(e)[:150]}"

    return LLMResult(False, error=last_error or "Unknown error calling the LLM.")
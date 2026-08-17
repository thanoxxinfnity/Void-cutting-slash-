"""Thin client for NVIDIA's OpenAI-compatible NIM inference API (integrate.api.nvidia.com).

Every tier of the swarm (fast chat + the 5-stage heavy cascade) talks to a
different model hosted behind this same endpoint, so the HTTP plumbing lives
here once instead of being copy-pasted into every agent module.
"""
import json

import requests

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TIMEOUT = 180


class NvidiaAPIError(RuntimeError):
    """Raised when the NVIDIA NIM API rejects a request or is unreachable."""


def chat_completion(api_key, model, messages, temperature=0.4, max_tokens=4096,
                     stream=False, timeout=DEFAULT_TIMEOUT):
    """Call POST /chat/completions. Returns the full text for stream=False,
    or a generator yielding token strings for stream=True."""
    if not api_key:
        raise NvidiaAPIError(
            "Missing NVIDIA API key. Add it in Settings (BYOK) before chatting."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }

    try:
        resp = requests.post(
            f"{NVIDIA_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            stream=stream,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise NvidiaAPIError(f"Could not reach NVIDIA API for model {model}: {exc}") from exc

    if resp.status_code != 200:
        raise NvidiaAPIError(
            f"NVIDIA API returned {resp.status_code} for model {model}: {resp.text[:500]}"
        )

    if not stream:
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _token_stream():
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if chunk == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            delta = obj.get("choices", [{}])[0].get("delta", {})
            token = delta.get("content")
            if token:
                yield token

    return _token_stream()


def list_models(api_key, timeout=30):
    """Return the list of model ids this API key can actually call. Used by
    Settings to verify a pasted key is genuine before saving it."""
    if not api_key:
        raise NvidiaAPIError("Missing NVIDIA API key.")
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(f"{NVIDIA_BASE_URL}/models", headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise NvidiaAPIError(f"Could not reach NVIDIA API: {exc}") from exc
    if resp.status_code != 200:
        raise NvidiaAPIError(f"NVIDIA API returned {resp.status_code}: {resp.text[:300]}")
    return [m["id"] for m in resp.json().get("data", [])]

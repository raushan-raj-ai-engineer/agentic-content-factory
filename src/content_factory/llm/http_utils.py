from __future__ import annotations

import asyncio
import json
import os
import random
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

_TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_DEFAULT_DELAYS = (2.0, 5.0, 10.0, 20.0, 30.0)
_MAX_RETRY_DELAY_SECONDS = 60.0


class LLMHTTPError(RuntimeError):
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        status_code: int,
        body: str,
        url: str,
    ) -> None:
        self.provider = provider
        self.model = model
        self.status_code = status_code
        self.body = body
        self.url = _redact_url(url)
        super().__init__(
            f"{provider} request failed: HTTP {status_code}\n"
            f"URL: {self.url}\nModel: {model}\nResponse: {body[:2000]}"
        )


class LLMQuotaExhaustedError(LLMHTTPError):
    """Non-transient project/day quota exhaustion.

    A new API key in the same project does not fix project-scoped quota. The
    caller should either wait for quota reset/increase or start a new workflow
    with another explicitly selected provider/model.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.args = (
            f"{self.args[0]}\n"
            "Quota appears to be exhausted for the current project/model. "
            "Retries were stopped because this is not a short-lived RPM/TPM burst. "
            "Check the project's active Gemini rate limits/quota in Google AI Studio, "
            "wait for reset or raise quota, then rerun with the same locked model."
        ,)


def _redact_url(url: str) -> str:
    """Remove credential-like query values before any URL reaches logs/errors."""
    try:
        parts = urlsplit(str(url))
        if not parts.query:
            return str(url)
        sensitive = {
            "key", "api_key", "apikey", "token", "access_token",
            "auth", "authorization", "secret", "client_secret",
        }
        query = []
        for name, value in parse_qsl(parts.query, keep_blank_values=True):
            query.append((name, "<redacted>" if name.casefold() in sensitive else value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return "<redacted-url>"


def retry_count(*provider_env_names: str) -> int:
    raw: str | None = None
    for name in (*provider_env_names, "LLM_HTTP_RETRIES"):
        if name and os.getenv(name) is not None:
            raw = os.getenv(name)
            break
    if raw is None:
        raw = "4"
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(0, min(6, value))


async def post_json_with_retries(
    *,
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, object],
    provider: str,
    model: str,
    timeout_seconds: float,
    stats: dict[str, Any] | None = None,
    retry_env_names: tuple[str, ...] = (),
) -> dict[str, object]:
    """POST JSON with same-provider/model transient retry.

    429 handling distinguishes short-lived rate pressure from project/day quota
    exhaustion. Transient responses honor Retry-After / Google RetryInfo when
    present, otherwise exponential delays with jitter are used. This utility
    never switches provider or model.
    """
    retries = retry_count(*retry_env_names)

    for attempt in range(retries + 1):
        try:
            response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            if attempt < retries:
                _bump(stats, "transient_retries")
                await _wait(provider, model, "timeout", attempt, retries)
                continue
            raise RuntimeError(
                f"{provider} timed out after {timeout_seconds:.0f}s. Model: {model}"
            ) from exc
        except httpx.RequestError as exc:
            if attempt < retries:
                _bump(stats, "transient_retries")
                await _wait(provider, model, exc.__class__.__name__, attempt, retries)
                continue
            detail = str(exc) or exc.__class__.__name__
            raise RuntimeError(
                f"Unable to reach {provider} at {_redact_url(url)}: {detail}. Model: {model}"
            ) from exc

        if response.status_code == 429 and _looks_like_daily_quota(response):
            _bump(stats, "quota_exhausted")
            raise LLMQuotaExhaustedError(
                provider=provider,
                model=model,
                status_code=response.status_code,
                body=response.text,
                url=url,
            )

        if response.status_code in _TRANSIENT_STATUS and attempt < retries:
            _bump(stats, "transient_retries")
            if response.status_code == 429:
                _bump(stats, "rate_limit_retries")
            delay = _retry_delay_seconds(response, attempt)
            await _wait(
                provider,
                model,
                _retry_reason(response),
                attempt,
                retries,
                delay_seconds=delay,
            )
            continue

        if response.is_error:
            raise LLMHTTPError(
                provider=provider,
                model=model,
                status_code=response.status_code,
                body=response.text,
                url=url,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"{provider} returned non-JSON data: {response.text[:1000]}"
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"{provider} returned unexpected JSON data.")
        _bump(stats, "requests")
        return data

    raise RuntimeError("Unreachable LLM HTTP retry state.")


def _response_payload(response: Any) -> object:
    try:
        return response.json()
    except Exception:
        return getattr(response, "text", "")


def _flatten_text(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _looks_like_daily_quota(response: Any) -> bool:
    """Detect non-transient daily/project quota language in a Gemini 429 body."""
    text = _flatten_text(_response_payload(response)).casefold()
    compact = re.sub(r"[^a-z0-9]+", "", text)
    markers = (
        "perday",
        "requestsperday",
        "tokensperday",
        "requestspday",
        "dailyquota",
        "daily quota",
        "quota per day",
        "rpd",
    )
    return any(marker in text or marker.replace(" ", "") in compact for marker in markers)


def _retry_reason(response: Any) -> str:
    status = int(getattr(response, "status_code", 0) or 0)
    if status != 429:
        return f"HTTP {status}"
    text = _flatten_text(_response_payload(response)).casefold()
    if any(token in text for token in ("per minute", "requestsperminute", "tokensperminute", "rpm", "tpm")):
        return "HTTP 429 rate-limit"
    return "HTTP 429 resource-exhausted"


def _retry_delay_seconds(response: Any, attempt: int) -> float:
    """Honor server hints before falling back to bounded exponential+jitter."""
    headers = getattr(response, "headers", None)
    if headers:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        parsed = _parse_delay(raw)
        if parsed is not None:
            return min(_MAX_RETRY_DELAY_SECONDS, parsed)

    payload = _response_payload(response)
    hinted = _find_retry_delay(payload)
    if hinted is not None:
        return min(_MAX_RETRY_DELAY_SECONDS, hinted)

    base = _DEFAULT_DELAYS[min(attempt, len(_DEFAULT_DELAYS) - 1)]
    # Small jitter prevents synchronized retries when multiple clients share quota.
    return min(_MAX_RETRY_DELAY_SECONDS, base * (1.0 + random.uniform(0.05, 0.25)))


def _find_retry_delay(value: object) -> float | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in {"retrydelay", "retry_delay", "retryafter", "retry_after"}:
                parsed = _parse_delay(child)
                if parsed is not None:
                    return parsed
            nested = _find_retry_delay(child)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _find_retry_delay(child)
            if nested is not None:
                return nested
    return None


def _parse_delay(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    raw = str(value).strip().casefold()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s|sec|secs|second|seconds)?", raw)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or "s"
    if unit == "ms":
        amount /= 1000.0
    return max(0.0, amount)


def _bump(stats: dict[str, Any] | None, key: str) -> None:
    if stats is None:
        return
    stats[key] = int(stats.get(key, 0)) + 1


async def _wait(
    provider: str,
    model: str,
    reason: str,
    attempt: int,
    retries: int,
    *,
    delay_seconds: float | None = None,
) -> None:
    wait = (
        float(delay_seconds)
        if delay_seconds is not None
        else _DEFAULT_DELAYS[min(attempt, len(_DEFAULT_DELAYS) - 1)]
    )
    wait = max(0.0, min(_MAX_RETRY_DELAY_SECONDS, wait))
    print(
        f"[LLM RETRY] provider={provider}, model={model}, reason={reason}; "
        f"retrying same locked model in {wait:.1f}s ({attempt + 1}/{retries})"
    )
    await asyncio.sleep(wait)

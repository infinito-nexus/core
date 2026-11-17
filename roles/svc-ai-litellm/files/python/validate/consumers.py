"""Validate all consumer keys through the gateway's native inference endpoints.

Inputs:
    stdin: JSON containing consumers (alias/key), models, base_url, timeout,
        workers, max_output_tokens and
        retry_policy (retries, delay and max_delay in seconds).
Outputs:
    Sanitized JSON checks; exit 1 if any key or inference request fails.
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

LMSTUDIO_ENGINE_FETCH_FAILED = "engine protocol predict request failed: fetch failed"


def retry_after_seconds(value):
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, seconds) if math.isfinite(seconds) else None


def request_check(base, key, path, body, timeout):
    headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    request = urllib.request.Request(  # noqa: S310 deployment-owned gateway URL
        base.rstrip("/") + path,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 deployment-owned gateway URL
            data = json.load(response)
            if path == "/v1/models":
                valid = isinstance(data.get("data"), list)
            elif path == "/v1/messages":
                valid = data.get("type") == "message" and any(
                    block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                    and block["text"].strip()
                    for block in (data.get("content") or [])
                    if isinstance(block, dict)
                )
            elif path == "/v1/responses":
                valid = (
                    data.get("object") == "response"
                    and not data.get("error")
                    and any(
                        block.get("type") == "output_text"
                        and isinstance(block.get("text"), str)
                        and block["text"].strip()
                        for item in (data.get("output") or [])
                        if isinstance(item, dict) and item.get("type") == "message"
                        for block in (item.get("content") or [])
                        if isinstance(block, dict)
                    )
                )
            else:
                valid = any(
                    isinstance(choice.get("message"), dict)
                    and isinstance(choice["message"].get("content"), str)
                    and choice["message"]["content"].strip()
                    for choice in (data.get("choices") or [])
                    if isinstance(choice, dict)
                )
            valid = bool(valid) and not data.get("error")
            return {
                "ok": valid,
                "http_status": response.status,
                "reason": "accepted" if valid else "invalid_response",
            }
    except urllib.error.HTTPError as error:
        retry_after = retry_after_seconds(
            error.headers.get("Retry-After") if error.headers else None
        )
        with error:
            text = error.read().decode(errors="replace").lower()
        signals = [
            term
            for term in (
                "credit balance",
                "budget",
                "invalid api key",
                "authentication",
                "key not found",
                "permission",
                "context",
                "model not found",
                "insufficient",
                "expired",
                "spend",
                "quota",
                "no endpoints available",
                "no endpoints found",
                "notfounderror",
                "rate limit",
                "cooldown",
                LMSTUDIO_ENGINE_FETCH_FAILED,
            )
            if term in text
        ]
        daily_quota = any(
            term in text
            for term in (
                "free-models-per-day",
                "requests per day",
                "daily limit",
                "daily quota",
            )
        )
        result = {
            "ok": False,
            "http_status": error.code,
            "reason": "provider_daily_quota_exhausted"
            if daily_quota
            else "gateway_rejected_request",
            "error_signals": signals,
        }
        if retry_after is not None:
            result["retry_after_seconds"] = retry_after
        return result
    except (urllib.error.URLError, OSError):
        return {"ok": False, "reason": "gateway_connection_failed"}
    except (ValueError, AttributeError, TypeError):
        return {"ok": False, "reason": "invalid_response"}


def request_with_retry(base, key, path, body, timeout, policy):
    waited = 0
    for attempt in range(policy["retries"] + 1):
        result = request_check(base, key, path, body, timeout)
        status = result.get("http_status")
        signals = result.get("error_signals") or []
        limited = (
            status == 429
            or (
                status is not None
                and status >= 500
                and any(signal in signals for signal in ("rate limit", "cooldown"))
            )
            or (status == 400 and LMSTUDIO_ENGINE_FETCH_FAILED in signals)
        )
        if any(
            signal in signals
            for signal in (
                "credit balance",
                "budget",
                "invalid api key",
                "authentication",
                "key not found",
                "permission",
                "expired",
                "insufficient",
            )
        ):
            limited = False
        result["attempts"] = attempt + 1
        result["retry_wait_seconds"] = waited
        if (
            result["ok"]
            or result.get("reason") == "provider_daily_quota_exhausted"
            or not limited
            or attempt == policy["retries"]
        ):
            return result
        wait = result.get("retry_after_seconds")
        wait = max(policy["delay"], wait) if wait is not None else policy["delay"]
        if wait > policy["max_delay"]:
            result["reason"] = "retry_after_exceeds_validation_limit"
            return result
        time.sleep(wait)
        waited += wait
    raise AssertionError("Retry policy requires a nonnegative retry count")


def validate(payload):
    for key in ("workers", "max_output_tokens"):
        if type(payload[key]) is not int or payload[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    policy = payload["retry_policy"]
    if type(policy["retries"]) is not int or policy["retries"] < 0:
        raise ValueError("retry_policy.retries must be a nonnegative integer")
    for key in ("delay", "max_delay"):
        if (
            type(policy[key]) not in (int, float)
            or not math.isfinite(policy[key])
            or policy[key] <= 0
        ):
            raise ValueError(f"retry_policy.{key} must be a positive finite number")
    if policy["delay"] > policy["max_delay"]:
        raise ValueError("retry_policy.delay must not exceed max_delay")

    def authenticate(consumer):
        key = consumer["key"]
        if not key:
            return {
                "consumer": consumer["alias"],
                "ok": False,
                "reason": "missing_consumer_key",
            }
        result = request_with_retry(
            payload["base_url"], key, "/v1/models", None, payload["timeout"], policy
        )
        return dict(result, consumer=consumer["alias"], endpoint="/v1/models")

    def probe(job):
        consumer, model, endpoint = job
        if endpoint == "/v1/responses":
            body = {
                "model": model,
                "max_output_tokens": payload["max_output_tokens"],
                "reasoning": {"effort": payload["codex_reasoning_effort"]},
                "input": "Reply OK.",
                "store": False,
            }
        else:
            body = {
                "model": model,
                "max_tokens": payload["max_output_tokens"],
                "messages": [{"role": "user", "content": "Reply OK."}],
            }
        result = request_with_retry(
            payload["base_url"],
            consumer["key"],
            endpoint,
            body,
            payload["timeout"],
            policy,
        )
        return dict(result, consumer=consumer["alias"], model=model, endpoint=endpoint)

    with ThreadPoolExecutor(max_workers=payload["workers"]) as pool:
        checks = list(pool.map(authenticate, payload["consumers"]))
        jobs = []
        for consumer, authentication in zip(payload["consumers"], checks, strict=True):
            if not authentication["ok"]:
                continue
            endpoints = ["/v1/chat/completions", "/v1/messages"]
            if consumer["alias"] == "dsk-gnt-codex":
                endpoints.append("/v1/responses")
            jobs.extend(
                (consumer, model, endpoint)
                for model in payload["models"]
                for endpoint in endpoints
            )
        checks.extend(pool.map(probe, jobs))
    return {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
        "inference_skipped": not bool(payload["models"]),
    }


def main():
    try:
        result = validate(json.load(sys.stdin))
    except Exception:
        result = {
            "ok": False,
            "reason": "invalid_validation_input_or_unexpected_failure",
        }
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

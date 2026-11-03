"""Validate one remote model using the provider key in the deployed container.

Inputs:
    stdin: JSON with provider, model, alias and optional api_base from remote_models;
        --batch accepts models, workers and the deployment-owned worker_source.
    LITELLM_TIMEOUT: request timeout in seconds.
    LITELLM_VALIDATION_OUTPUT_TOKENS: output-token budget including reasoning.
    <PROVIDER>_API_KEY: deployed provider credential.
Outputs:
    Sanitized JSON result; exit 1 on any failed provider request.
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout


def failure_reason(error):
    status = getattr(error, "status_code", None)
    message = str(error).lower()
    if any(
        term in message
        for term in (
            "credit balance",
            "insufficient_quota",
            "insufficient credits",
            "insufficient funds",
        )
    ):
        return (
            status,
            "insufficient_credit: check billing and the API key's account or organization",
        )
    reasons = {
        401: "invalid_key: check the deployed provider API key",
        402: "insufficient_credit: check provider billing and key spending limits",
        403: "access_denied: check key permissions, organization and spending limits",
        404: "model_unavailable: check the configured model and provider access",
        429: "rate_limited: check provider quota and request limits",
    }
    if status in reasons:
        return status, reasons[status]
    if isinstance(status, int) and status >= 500:
        return status, "provider_unavailable: provider returned a server error"
    return (
        status,
        "provider_request_failed: check model support, connectivity and provider status",
    )


def validate(declaration, timeout):
    provider = declaration["provider"]
    result = {"provider": provider, "alias": declaration["alias"]}
    key_name = f"{provider.upper()}_API_KEY"
    key = os.environ.get(key_name)
    if not key:
        return dict(
            result,
            ok=False,
            reason=f"missing_key: {key_name} is absent from the deployed container",
        )
    previous_logging = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            from litellm import completion

            endpoint = (
                {"api_base": declaration["api_base"]}
                if "api_base" in declaration
                else {}
            )
            response = completion(
                model=declaration["model"],
                api_key=key,
                messages=[{"role": "user", "content": "Reply OK."}],
                max_tokens=int(os.environ["LITELLM_VALIDATION_OUTPUT_TOKENS"]),
                timeout=timeout,
                num_retries=0,
                max_retries=0,
                **endpoint,
            )
            if not any(
                isinstance(choice.message.content, str)
                and choice.message.content.strip()
                for choice in response.choices
            ):
                return dict(
                    result,
                    ok=False,
                    reason="empty_response: provider returned no answer text",
                )
    except Exception as error:
        status, reason = failure_reason(error)
        return dict(result, ok=False, http_status=status, reason=reason)
    finally:
        logging.disable(previous_logging)
    return dict(result, ok=True)


def validate_all(payload, timeout):
    workers = payload["workers"]
    if type(workers) is not int or workers <= 0:
        raise ValueError("workers must be a positive integer")

    def probe(declaration):
        result = {"provider": declaration["provider"], "alias": declaration["alias"]}
        try:
            child = subprocess.run(
                [sys.executable, "-c", payload["worker_source"]],
                input=json.dumps(declaration),
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout + 30,
            )
            data = json.loads(child.stdout)
            if (
                child.returncode not in (0, 1)
                or type(data.get("ok")) is not bool
                or (child.returncode == 0) != data["ok"]
            ):
                return dict(result, ok=False, reason="provider_validator_failed")
            return {
                **result,
                **{
                    key: data[key]
                    for key in ("ok", "http_status", "reason")
                    if key in data
                },
            }
        except (ValueError, AttributeError, OSError, subprocess.SubprocessError):
            return dict(result, ok=False, reason="provider_validator_failed")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        checks = list(pool.map(probe, payload["models"]))
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def main():
    try:
        payload = json.load(sys.stdin)
        timeout = float(os.environ["LITELLM_TIMEOUT"])
        result = (
            validate_all(payload, timeout)
            if "--batch" in sys.argv
            else validate(payload, timeout)
        )
    except Exception:
        result = {"ok": False, "reason": "invalid_provider_validation_input"}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

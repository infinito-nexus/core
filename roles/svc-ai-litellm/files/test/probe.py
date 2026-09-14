"""Assert the gateway routes to exactly the backends this deployment enabled.

Runs inside the litellm container, where the gateway answers on loopback and
the backend containers resolve by name. Standard library only: the image ships
the litellm app, not a test toolchain.

Env (rendered into test.env from templates/test.env.j2):
    PORT               gateway http port inside the container
    MASTER_KEY         gateway master key
    CHAT_MODEL         the model every consumer asks for (LITELLM_CHAT_MODEL)
    CHAT_MODEL_SERVED  true|false, whether a backend can answer it
    EXPECTED_MODELS    JSON list the config template published
    LMSTUDIO_ALIASES   JSON list of aliases only LM Studio provides, rendered
                       whether or not the backend is deployed so the absent
                       case stays assertable
    REMOTE_ALIASES     JSON list of aliases a configured provider key publishes
                       (OpenAI, Anthropic, OpenRouter)
    OLLAMA_ENABLED     true|false
    LMSTUDIO_ENABLED   true|false
    RETRIES            completion attempts (default 10)
    SLEEP_SECONDS      wait between attempts (default 6)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request


def evaluate(
    *,
    served: set[str],
    expected: list[str],
    chat_model: str,
    chat_model_served: bool,
    ollama_enabled: bool,
    lmstudio_enabled: bool,
    lmstudio_aliases: list[str],
    remote_aliases: list[str],
) -> list[str]:
    """Every routing violation the published model list shows, as messages.

    Args:
        served: model ids the gateway answers ``/v1/models`` with.
        expected: model ids the rendered config declared.
        chat_model: the id consumers are configured to ask for.
        chat_model_served: whether any backend can answer *chat_model*.
        ollama_enabled: svc-ai-ollama is deployed on the gateway's host.
        lmstudio_enabled: svc-ai-lmstudio is deployed on the gateway's host.
        lmstudio_aliases: aliases only LM Studio provides, whatever is deployed.
        remote_aliases: aliases a configured remote provider key publishes.

    Returns:
        One message per violation; empty when the routing is consistent.
    """
    failures: list[str] = []

    undelivered = sorted(set(expected) - served)
    if undelivered:
        failures.append(
            f"the config declares {undelivered} but the gateway does not serve "
            f"them; the rendered config.yaml and the running gateway disagree"
        )

    exclusive = set(lmstudio_aliases)
    if lmstudio_enabled and not exclusive <= served:
        failures.append(
            f"svc-ai-lmstudio is deployed but the gateway does not serve "
            f"{sorted(exclusive - served)}; its models were declared and not routed"
        )
    if not lmstudio_enabled and exclusive & served:
        failures.append(
            f"svc-ai-lmstudio is not deployed yet the gateway publishes "
            f"{sorted(exclusive & served)}; a route stands without its backend"
        )

    unbacked = sorted(served - exclusive - set(remote_aliases))
    if not ollama_enabled and unbacked:
        failures.append(
            f"svc-ai-ollama is not deployed yet the gateway publishes {unbacked}"
        )

    if not chat_model_served:
        if served:
            failures.append(
                f"no backend is deployed but the gateway publishes {sorted(served)}"
            )
        return failures

    if chat_model not in served:
        failures.append(
            f"consumers are configured for '{chat_model}' (LITELLM_CHAT_MODEL, "
            f"built from the deployment inventory) but the gateway serves "
            f"{sorted(served)} (built from this host's group_names); the two "
            f"sources disagree"
        )

    return failures


def _call(base: str, key: str, path: str, payload: dict | None = None):
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(  # noqa: S310 - literal http:// to loopback
        base + path,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(  # noqa: S310 - literal http:// to loopback
        request, timeout=120
    ) as response:
        return json.loads(response.read().decode() or "{}")


def _completion(base: str, key: str, model: str, retries: int, pause: float) -> str:
    last_error = "no attempt ran"
    for attempt in range(1, retries + 1):
        try:
            completion = _call(
                base,
                key,
                "/v1/chat/completions",
                {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": "Reply with the word pong."}
                    ],
                    "max_tokens": 16,
                },
            )
            choices = completion.get("choices") or [{}]
            answer = (choices[0].get("message", {}).get("content") or "").strip()
            if answer:
                return answer
            last_error = "empty content"
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(pause)
    raise RuntimeError(last_error)


def main() -> int:
    key = os.environ["MASTER_KEY"]
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    chat_model = os.environ["CHAT_MODEL"].strip()
    chat_model_served = os.environ["CHAT_MODEL_SERVED"] == "true"
    retries = int(os.environ.get("RETRIES", "10"))
    pause = float(os.environ.get("SLEEP_SECONDS", "6"))

    listing = _call(base, key, "/v1/models")
    served = {entry.get("id") for entry in listing.get("data", [])}
    print(f"[INFO] gateway answered /v1/models, serving {sorted(served)}")

    failures = evaluate(
        served=served,
        expected=json.loads(os.environ["EXPECTED_MODELS"]),
        chat_model=chat_model,
        chat_model_served=chat_model_served,
        ollama_enabled=os.environ["OLLAMA_ENABLED"] == "true",
        lmstudio_enabled=os.environ["LMSTUDIO_ENABLED"] == "true",
        lmstudio_aliases=json.loads(os.environ["LMSTUDIO_ALIASES"]),
        remote_aliases=json.loads(os.environ["REMOTE_ALIASES"]),
    )

    if chat_model_served and not failures:
        try:
            answer = _completion(base, key, chat_model, retries, pause)
            print(f"[OK]   '{chat_model}' answered: {answer[:60]}")
        except RuntimeError as exc:
            failures.append(
                f"'{chat_model}' is published but answered nothing after "
                f"{retries} attempts; last failure: {exc}"
            )

    for failure in failures:
        print(f"[FAIL] {failure}", file=sys.stderr)
    if not failures:
        print("[OK]   the published routes match the deployed backends")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

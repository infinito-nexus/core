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
    router_alias: str = "",
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
        router_alias: the alias the pre-call hook rewrites. It is backed by no
            backend of its own, so it is accounted for separately and then held
            out of the backend arithmetic.

    Returns:
        One message per violation; empty when the routing is consistent.
    """
    failures: list[str] = []

    if router_alias:
        if served and router_alias not in served:
            failures.append(
                f"the config declares the router alias '{router_alias}' but the "
                f"gateway serves {sorted(served)}; consumers asking for it get a 400"
            )
        served = served - {router_alias}
        expected = [alias for alias in expected if alias != router_alias]

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


def _completion(
    base: str,
    key: str,
    model: str,
    retries: int,
    pause: float,
    prompt: str = "Reply with the word pong.",
) -> tuple[str, str]:
    """The answer and the model that produced it.

    The second half is what makes a router observable: the request names an
    alias, the response names whatever the pre-call hook rewrote it to.
    """
    last_error = "no attempt ran"
    for attempt in range(1, retries + 1):
        try:
            completion = _call(
                base,
                key,
                "/v1/chat/completions",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 16,
                },
            )
            choices = completion.get("choices") or [{}]
            answer = (choices[0].get("message", {}).get("content") or "").strip()
            if answer:
                return answer, str(completion.get("model") or "")
            last_error = "empty content"
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(pause)
    raise RuntimeError(last_error)


def _declared_window(windows: dict, served: str):
    """The window declared for *served*, whichever name the response carries.

    litellm sets ``model_response.model`` to the resolved model rather than the
    alias, so an answer can come back as ``ollama/qwen2.5:0.5b`` while the
    windows are keyed on ``qwen2.5:0.5b``. Looking up only the literal name
    would find nothing and pass every answer, which is worse than no check.
    """
    for key in (served, served.split("/", 1)[-1]):
        if key in windows:
            return windows[key]
    return None


def route_verdict(
    router_alias: str, windows: dict, served: str, needed_tokens: int
) -> str:
    """Why this answer does not prove the router worked, or the empty string.

    Args:
        router_alias: the alias the request named.
        windows: alias -> declared context window, for the routes that declare one.
        served: the model the response named.
        needed_tokens: what the prompt demands, as the hook would estimate it.

    Returns:
        One message, empty when the answer is a legitimate routing outcome.
    """
    if not served:
        return f"'{router_alias}' answered without naming a model, so nothing shows which route ran"
    if served == router_alias:
        return (
            f"'{router_alias}' answered as itself; the pre-call hook did not rewrite "
            f"the model, so the request took the alias's own fallback route"
        )
    window = _declared_window(windows, served)
    if window is not None and int(window) < needed_tokens:
        return (
            f"'{router_alias}' routed a prompt of about {needed_tokens} tokens to "
            f"'{served}', whose declared window is {window}; the eligibility filter "
            f"did not exclude it"
        )
    return ""


def oversized_prompt(smallest_window: int) -> tuple[str, int]:
    """A prompt no route with *smallest_window* can hold, and its token demand.

    The hook estimates three characters per token and errs high, so four
    characters per token clears the smallest window whichever constant it
    carries, while staying far inside the next one up.
    """
    characters = smallest_window * 4
    return "x " * (characters // 2), characters // 3


def _probe_router(
    base: str,
    key: str,
    router_alias: str,
    windows: dict,
    retries: int,
    pause: float,
) -> list[str]:
    """Whether the alias routes, or only answers.

    The alias falls back to the first published route, which is the first
    preloaded model and therefore the one with the smallest window. A prompt
    that route cannot hold separates a routed request from a fallback: without
    the hook the answer comes back from a model whose window is too small.
    """
    failures: list[str] = []
    smallest = min(windows.values())
    prompt, needed = oversized_prompt(smallest)
    try:
        answer, served = _completion(
            base, key, router_alias, retries, pause, prompt=prompt
        )
    except RuntimeError as exc:
        return [
            (
                f"'{router_alias}' answered nothing for a prompt of about {needed} "
                f"tokens after {retries} attempts; last failure: {exc}"
            )
        ]
    verdict = route_verdict(router_alias, windows, served, needed)
    if verdict:
        failures.append(verdict)
    else:
        print(
            f"[OK]   '{router_alias}' routed about {needed} tokens to '{served}' "
            f"(window {windows.get(served, 'undeclared')}), answered: {answer[:40]}"
        )
    return failures


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
        router_alias=os.environ.get("ROUTER_ALIAS", "").strip(),
    )

    if chat_model_served and not failures:
        try:
            answer, _ = _completion(base, key, chat_model, retries, pause)
            print(f"[OK]   '{chat_model}' answered: {answer[:60]}")
        except RuntimeError as exc:
            failures.append(
                f"'{chat_model}' is published but answered nothing after "
                f"{retries} attempts; last failure: {exc}"
            )

    router_alias = os.environ.get("ROUTER_ALIAS", "").strip()
    windows = {
        alias: int(window)
        for alias, window in json.loads(
            os.environ.get("ROUTER_WINDOWS", "{}") or "{}"
        ).items()
        if alias in served
    }
    if router_alias and len(windows) > 1 and not failures:
        failures.extend(_probe_router(base, key, router_alias, windows, retries, pause))

    for failure in failures:
        print(f"[FAIL] {failure}", file=sys.stderr)
    if not failures:
        print("[OK]   the published routes match the deployed backends")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

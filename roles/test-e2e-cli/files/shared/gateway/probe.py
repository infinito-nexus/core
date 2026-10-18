"""Check that a workstation agent's configured gateway actually answers it.

Env (rendered into test.env from the staging role's templates/test.env.j2):
    GATEWAY_CONFIG_PATH   the config file the role writes
    GATEWAY_URL           the OpenAI-compatible base URL the agent was pointed at
    GATEWAY_KEY           the key the agent presents
    GATEWAY_MODEL         the alias the agent asks for
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 300
PROMPT = "Reply with the single word pong."


def failures() -> list[str]:
    config_path = Path(os.environ["GATEWAY_CONFIG_PATH"])
    url = os.environ["GATEWAY_URL"].rstrip("/")
    model = os.environ["GATEWAY_MODEL"]
    found: list[str] = []

    if not config_path.is_file():
        return [
            f"{config_path} does not exist, so the agent was never pointed anywhere"
        ]

    written = config_path.read_text(encoding="utf-8")
    if url not in written:
        found.append(
            f"{config_path} does not name {url}, so the agent would reach the vendor API"
        )

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": 16,
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310 the URL is the loopback gateway this deployment published
        f"{url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {os.environ['GATEWAY_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 loopback gateway
            body = json.loads(response.read())
    except urllib.error.HTTPError as error:
        return [*found, f"the gateway refused the agent's key with HTTP {error.code}"]
    except (urllib.error.URLError, TimeoutError) as error:
        return [*found, f"the gateway at {url} could not be reached: {error}"]

    choices = body.get("choices") or [{}]
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        found.append(f"{model} answered through the gateway without any content")
    else:
        print(f"[OK]   {model} answered through {url}: {content[:40]}")
    return found


def main() -> int:
    found = failures()
    for failure in found:
        print(f"[FAIL] {failure}", file=sys.stderr)
    if not found:
        print("[OK]   the agent reaches the gateway and gets an answer")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

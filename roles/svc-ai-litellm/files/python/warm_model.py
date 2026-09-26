"""Force the gateway to load its chat model before any consumer prompts it.

A backend pulls its preload model at deploy time but only loads it into memory
on the first inference. That cold load outlives the reverse proxy's read
timeout, so the first consumer request comes back as a 504 instead of an answer
while every later one succeeds. Warming here moves the cost into the deploy.

Environment:
    LITELLM_MASTER_KEY: master key the gateway accepts, read from its own
        environment rather than passed in.
    LITELLM_PORT:  port the gateway listens on inside its own container.
    LITELLM_MODEL: model name to warm.
"""

from __future__ import annotations

import json
import os
import urllib.request

MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]
PORT = os.environ["LITELLM_PORT"]
MODEL = os.environ["LITELLM_MODEL"]
TIMEOUT = 900

payload = json.dumps(
    {
        "model": MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
).encode()

request = urllib.request.Request(
    f"http://127.0.0.1:{PORT}/v1/chat/completions",
    data=payload,
    headers={
        "Authorization": f"Bearer {MASTER_KEY}",
        "Content-Type": "application/json",
    },
    method="POST",
)

with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 fixed internal http origin
    response.read()

print(f"WARMED {MODEL}")

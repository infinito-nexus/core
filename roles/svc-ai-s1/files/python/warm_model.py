"""Put one question to the decider so the deploy pays its first inference.

svc-ai-litellm's router hook allows one attempt of services.s1.request_timeout
and refuses to route on any error rather than substituting a decider, so a
consumer that arrives before the server answers gets a 400 while every later
one is served. Asking here moves that first answer into the deploy.

The request is the contract both flavors serve, POST /v1/systemone, so the
same script warms whichever one the flavor selected.

Environment (flavor-neutral, rendered by templates/env.j2):
    S1_PORT: port the decider listens on inside its own container.
    S1_MODEL_ALIAS: alias the request names; a flavor that resolves its own
        checkpoint ignores the field rather than failing on it.
    S1_API_KEY: the accepted key, read from the container's own environment
        rather than passed in.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

PORT = os.environ["S1_PORT"]
MODEL = os.environ["S1_MODEL_ALIAS"]
KEY = os.environ["S1_API_KEY"]
QUESTION = "warmup"
TIMEOUT = 900

payload = json.dumps(
    {
        "state": "It rained all morning and the forecast promises more storms tonight.",
        "model": MODEL,
        "questions": {
            QUESTION: {
                "type": "choice",
                "instructions": "Pick the topic this text belongs to.",
                "criteria": {
                    "weather": "the text is about weather, rain, storms or a forecast",
                    "cooking": "the text is about food, recipes, ingredients or a kitchen",
                },
            }
        },
    }
).encode()

request = urllib.request.Request(
    f"http://127.0.0.1:{PORT}/v1/systemone",
    data=payload,
    headers={
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
    },
    method="POST",
)

with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 loopback inside the container
    body = json.loads(response.read())

if not (body.get("answers") or {}).get(QUESTION):
    print(f"the decider answered without an answer to {QUESTION!r}", file=sys.stderr)
    sys.exit(1)

"""Force jeff to load its decider before the router asks it to choose a route.

The healthcheck answers as soon as the HTTP server binds, while the model
loads on the first real question. svc-ai-litellm's router hook allows one
attempt of services.jeff.request_timeout and refuses to route on any error
rather than substituting a decider, so a consumer that arrives during that
window gets a 400 while every later one is served. Warming here moves the cost
into the deploy.

Environment:
    JEFF_PORT: port jeff listens on inside its own container.
    JEFF_MODEL_ALIASES: comma-separated aliases; the first one is asked.
    JEFF_API_KEYS: comma-separated accepted keys, read from jeff's own
        environment rather than passed in.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

PORT = os.environ["JEFF_PORT"]
MODEL = os.environ["JEFF_MODEL_ALIASES"].split(",")[0].strip()
KEY = os.environ["JEFF_API_KEYS"].split(",")[0].strip()
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
    print(f"jeff answered without an answer to {QUESTION!r}", file=sys.stderr)
    sys.exit(1)

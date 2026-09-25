"""
Environment:
    PORT:     broker port.
    KEY:      broker key; empty sends no Authorization header.
    OWNER:    X-OpenWebUI-User-Id to send.
    EMAIL:    X-OpenWebUI-User-Email to send.
    MODEL:    agent platform.
    TIMEOUT:  seconds the request may take.

Prints ``STATUS <code>`` and, on 200, ``CONTENT <first 80 chars>``.
"""

import json
import os
import urllib.error
import urllib.request

request = urllib.request.Request(
    f"http://127.0.0.1:{os.environ['PORT']}/v1/chat/completions",
    data=json.dumps(
        {
            "model": os.environ["MODEL"],
            "messages": [
                {"role": "user", "content": "Reply with exactly the word: pong"}
            ],
            "stream": False,
        }
    ).encode(),
    method="POST",
)
request.add_header("Content-Type", "application/json")
if os.environ["KEY"]:
    request.add_header("Authorization", f"Bearer {os.environ['KEY']}")
request.add_header("X-OpenWebUI-User-Id", os.environ["OWNER"])
request.add_header("X-OpenWebUI-User-Email", os.environ["EMAIL"])
try:
    with urllib.request.urlopen(  # noqa: S310 - fixed http://127.0.0.1 target
        request, timeout=int(os.environ["TIMEOUT"])
    ) as response:
        body = json.loads(response.read())
        print(f"STATUS {response.status}")
        content = (body.get("choices") or [{}])[0].get("message", {}).get(
            "content"
        ) or ""
        print(f"CONTENT {content.strip()[:80]}")
except urllib.error.HTTPError as error:
    print(f"STATUS {error.code}")

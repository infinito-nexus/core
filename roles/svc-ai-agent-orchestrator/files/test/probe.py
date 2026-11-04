"""
Environment:
    PORT:          orchestrator port.
    METHOD:        HTTP method.
    REQ_PATH:      request path.
    KEY:           bearer presented when set.
    SECRET:        when set, an X-Hub-Signature-256 over BODY is computed and sent.
    SIG_OVERRIDE:  when set, this literal signature header is sent instead.
    DELIVERY:      X-Delivery-Id header when set.
    BODY:          request body.
    TIMEOUT:       seconds the request may take.

Prints ``STATUS <code>``.
"""

import hashlib
import hmac
import os
import urllib.error
import urllib.request

body = os.environ.get("BODY", "").encode()
method = os.environ["METHOD"]
request = urllib.request.Request(
    f"http://127.0.0.1:{os.environ['PORT']}{os.environ['REQ_PATH']}",
    data=body if method == "POST" else None,
    method=method,
)
request.add_header("Content-Type", "application/json")
if os.environ.get("KEY"):
    request.add_header("Authorization", f"Bearer {os.environ['KEY']}")
if os.environ.get("SECRET"):
    digest = hmac.new(os.environ["SECRET"].encode(), body, hashlib.sha256).hexdigest()
    request.add_header("X-Hub-Signature-256", f"sha256={digest}")
if os.environ.get("SIG_OVERRIDE"):
    request.add_header("X-Hub-Signature-256", os.environ["SIG_OVERRIDE"])
if os.environ.get("DELIVERY"):
    request.add_header("X-Delivery-Id", os.environ["DELIVERY"])
try:
    with urllib.request.urlopen(  # noqa: S310 - fixed http://127.0.0.1 target
        request, timeout=int(os.environ["TIMEOUT"])
    ) as response:
        print(f"STATUS {response.status}")
except urllib.error.HTTPError as error:
    print(f"STATUS {error.code}")

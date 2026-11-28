"""
Environment:
    PORT:      provisioner port.
    METHOD:    HTTP method.
    REQ_PATH:  request path.
    KEY:       bearer presented when set.
    BODY:      request body.
    TIMEOUT:   seconds the request may take.

Prints ``STATUS <code>``.
"""

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
try:
    with urllib.request.urlopen(  # noqa: S310 - fixed http://127.0.0.1 target
        request, timeout=int(os.environ["TIMEOUT"])
    ) as response:
        print(f"STATUS {response.status}")
except urllib.error.HTTPError as error:
    print(f"STATUS {error.code}")

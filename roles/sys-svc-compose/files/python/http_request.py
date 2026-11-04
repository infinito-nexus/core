"""Send one HTTP request and print the answer as JSON.

Args (environment):
    HTTP_METHOD: request method.
    HTTP_URL: absolute http:// URL.
    HTTP_BODY: JSON request body; an empty string sends none.

Output:
    ``{"status": int, "content_type": str, "content": str}`` on stdout. An
    HTTP error status is an answer; a connection failure exits non-zero.
    Proxy variables of the environment are ignored.
"""

import json
import os
import sys
import urllib.error
import urllib.request

body = os.environ["HTTP_BODY"]
request = urllib.request.Request(  # noqa: S310 - caller-fixed http:// URL inside the app's own namespace
    os.environ["HTTP_URL"],
    data=body.encode() if body else None,
    headers={"Content-Type": "application/json"} if body else {},
    method=os.environ["HTTP_METHOD"],
)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(request, timeout=60) as response:
        status, headers, content = response.status, response.headers, response.read()
except urllib.error.HTTPError as error:
    status, headers, content = error.code, error.headers, error.read()
json.dump(
    {
        "status": status,
        "content_type": headers.get("Content-Type", ""),
        "content": content.decode(errors="replace"),
    },
    sys.stdout,
)

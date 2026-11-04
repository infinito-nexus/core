"""Send one HTTP request and print the answer as JSON.

Args (module global, prepended on stdin by lookup('http_request_program')):
    BODY_B64: base64 of the JSON request body; an empty body sends none.
    HEADERS_B64: base64 of a JSON object of extra request headers.

Args (environment):
    HTTP_METHOD: request method.
    HTTP_URL: absolute http:// URL.

Output:
    ``{"status": int, "content_type": str, "content": str}`` on stdout. An
    HTTP error status is an answer; a connection failure exits non-zero.
    Proxy variables of the environment are ignored.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

body = base64.b64decode(globals()["BODY_B64"]).decode()
headers = {"Content-Type": "application/json"} if body else {}
headers.update(json.loads(base64.b64decode(globals()["HEADERS_B64"]).decode()))
request = urllib.request.Request(  # noqa: S310 - caller-fixed http:// URL inside the app's own namespace
    os.environ["HTTP_URL"],
    data=body.encode() if body else None,
    headers=headers,
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

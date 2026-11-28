"""Upload one PNG instance logo to PeerTube as ``logofile`` form data.

Args (module globals, prepended on stdin by the caller):
    LOGO_B64: base64 of the PNG file.
    HEADERS_B64: base64 of a JSON object of request headers (Host, Authorization).

Args (environment):
    HTTP_URL: absolute http:// URL of the instance-logo pick endpoint.

Output:
    The HTTP status on stdout. An HTTP error status is an answer; a connection
    failure exits non-zero. Proxy variables of the environment are ignored.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

boundary = uuid.uuid4().hex
body = (
    (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="logofile"; filename="logo.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode()
    + base64.b64decode(globals()["LOGO_B64"])
    + f"\r\n--{boundary}--\r\n".encode()
)
headers = json.loads(base64.b64decode(globals()["HEADERS_B64"]).decode())
headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
request = urllib.request.Request(  # noqa: S310 - caller-fixed http:// URL inside PeerTube's own namespace
    os.environ["HTTP_URL"], data=body, headers=headers, method="POST"
)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(request, timeout=60) as response:
        status = response.status
except urllib.error.HTTPError as error:
    status = error.code
sys.stdout.write(f"{status}\n")

"""Send one HTTP request to XWiki and print the answer as JSON.

Args (module globals, set by lines the caller prepends to this script on stdin):
    HEADERS_B64: base64 of a JSON object of request headers.
    BODY_B64: base64 of the request body, sent verbatim; an empty body sends none.
    Headers and body carry credentials and cookies, which an environment
    variable would expose on the process command line.

Args (environment):
    HTTP_METHOD: request method.
    HTTP_URL: absolute http:// URL.
    HTTP_FOLLOW_REDIRECTS: ``safe`` follows redirects of GET and HEAD
        requests, ``none`` answers with the redirect itself.
    HTTP_TIMEOUT: socket timeout in seconds.

Output:
    ``{"status": int, "url": str, "redirected": bool, "headers": dict,
    "cookies_string": str, "content": str}`` on stdout. Header names are lower
    case and a repeated header joins its values with ``", "``.
    ``cookies_string`` holds every cookie set along the way as
    ``name=value; ...``. An HTTP error status is an answer; a connection
    failure exits non-zero.
"""

import base64
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

FOLLOW_REDIRECTS = {"safe": True, "none": False}[os.environ["HTTP_FOLLOW_REDIRECTS"]]


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if FOLLOW_REDIRECTS and req.get_method() in {"GET", "HEAD"}:
            return super().redirect_request(req, fp, code, msg, headers, newurl)
        return None


def _joined(headers):
    joined = {}
    for name, value in headers.items():
        key = name.lower()
        joined[key] = f"{joined[key]}, {value}" if key in joined else value
    return joined


url = os.environ["HTTP_URL"]
body = base64.b64decode(globals()["BODY_B64"]).decode()
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _Redirects(),
    urllib.request.HTTPCookieProcessor(jar),
)
request = urllib.request.Request(  # noqa: S310 - caller-fixed http:// URL inside XWiki's own network namespace
    url,
    data=body.encode() if body else None,
    headers=json.loads(base64.b64decode(globals()["HEADERS_B64"])),
    method=os.environ["HTTP_METHOD"],
)
try:
    answer = opener.open(request, timeout=int(os.environ["HTTP_TIMEOUT"]))
except urllib.error.HTTPError as error:
    answer = error
json.dump(
    {
        "status": answer.status,
        "url": answer.url,
        "redirected": answer.url != url,
        "headers": _joined(answer.headers),
        "cookies_string": "; ".join(f"{cookie.name}={cookie.value}" for cookie in jar),
        "content": answer.read().decode(),
    },
    sys.stdout,
)

import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = "2022-11-28"
NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')


class CheckError(Exception):
    pass


def allowed_url(url):
    """Return whether a URL may be opened: https, or plain http only to a loopback or dotless container-internal host, where the tests run their API stub.

    Args:
        url: the URL, configured or taken from a Link header.
    """
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    try:
        internal = ipaddress.ip_address(host).is_loopback
    except ValueError:
        internal = host == "localhost" or (host != "" and "." not in host)
    return parts.scheme == "https" or (parts.scheme == "http" and internal)


def failure_reason(status, body, headers):
    """Return why a GitHub API call failed, naming the rate limit when it is the cause.

    Args:
        status: the HTTP status.
        body: the response body.
        headers: the response headers, None when there were none.
    """
    try:
        message = str(json.loads(body).get("message", ""))
    except (ValueError, AttributeError):
        message = ""
    remaining = headers.get("X-RateLimit-Remaining") if headers else None
    if status == 429 or (
        status == 403 and (remaining == "0" or "rate limit" in message.lower())
    ):
        reset = headers.get("X-RateLimit-Reset", "unknown") if headers else "unknown"
        return f"HTTP {status}: rate limit exceeded, resets at epoch {reset}"
    return f"HTTP {status}: {message or 'no message'}"


class Api:
    def __init__(self, base_url, token, timeout):
        if not allowed_url(base_url):
            raise ValueError(
                f"refusing GitHub API URL {base_url}: https is required outside loopback and container-internal hosts"
            )
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _open(self, url):
        if not allowed_url(url):
            raise CheckError(f"refusing to open {url}: not https")
        request = urllib.request.Request(  # noqa: S310 - allowed_url admits only https, or http to a loopback or container-internal stub
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "infinito-github-settings",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - scheme checked by allowed_url
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers
        except (urllib.error.URLError, OSError) as error:
            raise CheckError(
                f"GitHub API unreachable: {getattr(error, 'reason', error)}"
            ) from error

    def _get(self, url, missing_ok):
        status, body, headers = self._open(url)
        if status == 404 and missing_ok:
            return None, headers
        if status != 200:
            raise CheckError(failure_reason(status, body, headers))
        try:
            return json.loads(body or b"null"), headers
        except ValueError as error:
            raise CheckError(f"HTTP {status}: not JSON") from error

    def get(self, path, missing_ok=False):
        return self._get(self.base_url + path, missing_ok)[0]

    def get_all(self, path):
        items = []
        url = self.base_url + path
        while url:
            page, headers = self._get(url, False)
            if not isinstance(page, list):
                raise CheckError(f"{path}: expected a list")
            items.extend(page)
            match = NEXT_LINK.search(headers.get("Link", "") if headers else "")
            url = match.group(1) if match else None
        return items

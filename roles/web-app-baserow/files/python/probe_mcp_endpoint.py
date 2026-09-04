# nocheck: mirrored-unit-test - reads MCP_BASE_URL and the endpoint key from the
# container environment at import and then drives a live SSE handshake; the module
# cannot be loaded outside the running Baserow container
import os
import sys
import urllib.error
import urllib.request

base_url = os.environ["MCP_BASE_URL"].rstrip("/")
endpoint_path = os.environ["MCP_ENDPOINT_PATH"]
key = os.environ["MCP_ENDPOINT_KEY"]

TIMEOUT = 15
STREAM_LINES = 4

TRANSIENT_STATUS = frozenset({0, 429, 502, 503, 504})


def refuse(message, status):
    marker = "PENDING" if status in TRANSIENT_STATUS else "REJECTED"
    sys.stderr.write(f"{marker} {message}\n")
    sys.exit(1)


def probe(candidate):
    """Return (status, content_type, first stream lines) of an SSE GET.

    Args:
        candidate: endpoint key placed in the URL path.
    """
    url = f"{base_url}{endpoint_path}/{candidate}/sse"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310 fixed internal http origin
            lines = [response.readline() for _ in range(STREAM_LINES)]
            return response.status, response.headers.get("Content-Type", ""), lines
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), []
    except OSError:
        return 0, "", []


status, content_type, _ = probe("0" * len(key))
if status != 401:
    refuse(f"unauthenticated probe answered {status} {content_type}", status)

status, content_type, lines = probe(key)
if status != 200 or "text/event-stream" not in content_type:
    refuse(f"authenticated probe answered {status} {content_type}", status)

stream = b"".join(lines)
if b"event: endpoint" not in stream:
    refuse(f"authenticated probe streamed {stream!r}", None)

print("OK")

import os
import sys
import urllib.error
import urllib.request

base_url = os.environ["MCP_BASE_URL"].rstrip("/")
endpoint_path = os.environ["MCP_ENDPOINT_PATH"]
key = os.environ["MCP_ENDPOINT_KEY"]

TIMEOUT = 15
STREAM_LINES = 4


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


status, content_type, _ = probe("0" * len(key))
if status != 401:
    sys.stderr.write(
        f"REJECTED unauthenticated probe answered {status} {content_type}\n"
    )
    sys.exit(1)

status, content_type, lines = probe(key)
if status != 200 or "text/event-stream" not in content_type:
    sys.stderr.write(f"REJECTED authenticated probe answered {status} {content_type}\n")
    sys.exit(1)

stream = b"".join(lines)
if b"event: endpoint" not in stream:
    sys.stderr.write(f"REJECTED authenticated probe streamed {stream!r}\n")
    sys.exit(1)

print("OK")

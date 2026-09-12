import contextlib
import json
import os
import urllib.error
import urllib.request

TIMEOUT = 30


def ensure_key(entry, call):
    """Give the consumer the key it was issued, whatever holds the alias now.

    An inventory re-initialization mints a new key while the proxy database
    keeps the previous one under the same alias, and the alias is unique, so
    creating the new key is refused until the stale one is gone.

    Args:
        entry: mapping with an ``alias`` and the ``key`` it must carry.
        call: ``(method, path, body=None)`` performing one HTTP request.

    Returns:
        True when the key had to be created, False when it already existed.
    """
    with contextlib.suppress(urllib.error.HTTPError):
        call("GET", "/key/info?key=" + entry["key"])
        return False
    with contextlib.suppress(urllib.error.HTTPError):
        call("POST", "/key/delete", {"key_aliases": [entry["alias"]]})
    call("POST", "/key/generate", {"key": entry["key"], "key_alias": entry["alias"]})
    return True


def http_call(base, headers):
    """Return a ``call`` bound to one proxy.

    Args:
        base: scheme and authority of the proxy, without a trailing slash.
        headers: headers sent with every request, carrying the master key.
    """

    def call(method, path, body=None):
        request = urllib.request.Request(  # noqa: S310 fixed internal http origin
            base + path,
            data=(json.dumps(body).encode() if body is not None else None),
            headers=headers,
            method=method,
        )
        return urllib.request.urlopen(request, timeout=TIMEOUT)  # noqa: S310 fixed internal http origin

    return call


def main():
    call = http_call(
        "http://localhost:" + os.environ["LITELLM_PORT"],
        {
            "Authorization": "Bearer " + os.environ["LITELLM_MK"],
            "Content-Type": "application/json",
        },
    )
    for entry in json.loads(os.environ["LITELLM_KEYS_PAYLOAD"]):
        if ensure_key(entry, call):
            print("CHANGED " + entry["alias"])


if __name__ == "__main__":
    main()

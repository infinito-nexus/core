import contextlib
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 30
HOST_ALIAS_PREFIX = "host:"
PAGE_SIZE = 100


def ensure_key(entry, call):
    """Give the consumer the key it was issued, whatever holds the alias now.

    An inventory re-initialization mints a new key while the proxy database
    keeps the previous one under the same alias, and the alias is unique, so
    creating the new key is refused until the stale one is gone.

    Args:
        entry: mapping with an ``alias`` and the ``key`` it must carry.
        call: ``(method, path, body=None)`` performing one HTTP request and
            returning a readable JSON response.

    Returns:
        True when the key had to be created, False when it already existed.

    Raises:
        urllib.error.HTTPError: the lookup or ``/key/generate`` failed.
        urllib.error.URLError: the proxy could not be reached at all.
    """
    found = json.load(call("POST", "/v2/key/info", {"keys": [entry["key"]]}))
    if found.get("info"):
        return False
    with contextlib.suppress(urllib.error.HTTPError):
        call("POST", "/key/delete", {"key_aliases": [entry["alias"]]})
    call("POST", "/key/generate", {"key": entry["key"], "key_alias": entry["alias"]})
    return True


def held_host_aliases(call):
    """Return every consuming-host alias the proxy holds a key under.

    Args:
        call: ``(method, path, body=None)`` performing one HTTP request and
            returning a readable JSON response.
    """
    held = set()
    page = 1
    while True:
        listing = json.load(
            call(
                "GET",
                f"/key/list?return_full_object=true&size={PAGE_SIZE}&page={page}",
            )
        )
        for key in listing.get("keys") or []:
            alias = key.get("key_alias") if isinstance(key, dict) else None
            if isinstance(alias, str) and alias.startswith(HOST_ALIAS_PREFIX):
                held.add(alias)
        if page >= int(listing.get("total_pages") or 1):
            return held
        page += 1


def revoke_stale_host_keys(wanted, call):
    """Delete the key of every consuming host the inventory no longer names.

    A host whose gateway value was removed keeps a working key in the proxy
    database until something deletes it, because ``ensure_key`` only ever
    adds. Local consumer aliases are never touched here.

    Args:
        wanted: every alias this deploy registers.
        call: ``(method, path, body=None)`` performing one HTTP request.

    Returns:
        The aliases whose key was deleted, sorted.
    """
    stale = sorted(held_host_aliases(call) - set(wanted))
    if stale:
        call("POST", "/key/delete", {"key_aliases": stale})
    return stale


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
            "Authorization": "Bearer " + os.environ["LITELLM_MASTER_KEY"],
            "Content-Type": "application/json",
        },
    )
    entries = json.load(sys.stdin)
    for entry in entries:
        if ensure_key(entry, call):
            print("CHANGED " + entry["alias"])
    for alias in revoke_stale_host_keys([entry["alias"] for entry in entries], call):
        print("REVOKED " + alias)


if __name__ == "__main__":
    main()

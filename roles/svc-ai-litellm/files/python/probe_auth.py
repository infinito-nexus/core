"""Prove the gateway is closed, keyed per consumer, and revocable in isolation.

A gateway that answers an unauthenticated caller hands every model on the
deployment to anything that can reach the overlay, and a revocation that takes
other consumers down with it is a revocation nobody dares to use. Both failures
are silent: the deploy is green either way and the first symptom is either a
stranger's bill or an outage.

The probe mints its own throwaway key, revokes that one, and shows a real
consumer key still working afterwards, so it proves isolation without touching
any credential a consumer depends on.

Environment:
    LITELLM_MK:   master key the gateway accepts.
    LITELLM_PORT: port the gateway listens on inside its own container.
    LITELLM_KEY:  a live consumer virtual key that must survive the revocation.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import urllib.error
import urllib.request

TIMEOUT = 30
PROBE_ALIAS = "infinito-auth-probe"
REVOCATION_ATTEMPTS = 10
REVOCATION_DELAY = 3
UNAUTHORIZED = (401, 403)


class ProbeError(RuntimeError):
    """The gateway answered in a way that fails the authentication contract."""


def status_of(base, key):
    """Return the status the gateway answers ``GET /v1/models`` with.

    Args:
        base: scheme and authority of the gateway, without a trailing slash.
        key: bearer token to send, or None to send no ``Authorization`` header.
    """
    headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
    request = urllib.request.Request(  # noqa: S310 fixed internal http origin
        base + "/v1/models", headers=headers, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 fixed internal http origin
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def admin_call(base, master_key):
    """Return a ``call(method, path, body)`` authenticated as the gateway admin.

    Args:
        base: scheme and authority of the gateway, without a trailing slash.
        master_key: the gateway's master key.
    """

    def call(method, path, body=None):
        request = urllib.request.Request(  # noqa: S310 fixed internal http origin
            base + path,
            data=(json.dumps(body).encode() if body is not None else None),
            headers={
                "Authorization": f"Bearer {master_key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 fixed internal http origin
            return json.loads(response.read() or b"{}")

    return call


def await_rejection(get_status, key, sleep):
    """Return the status of a revoked key once the gateway stops honouring it.

    LiteLLM serves keys from an in-process cache, so a deletion the database
    already accepted keeps answering 200 for a moment.

    Args:
        get_status: ``(key) -> int`` returning the gateway's status for a key.
        key: the revoked key.
        sleep: ``(seconds) -> None`` used between attempts.
    """
    status = get_status(key)
    for _ in range(REVOCATION_ATTEMPTS):
        if status in UNAUTHORIZED:
            return status
        sleep(REVOCATION_DELAY)
        status = get_status(key)
    return status


def probe(get_status, call, consumer_key, sleep=time.sleep):
    """Run the whole authentication contract, raising on the first breach.

    Args:
        get_status: ``(key) -> int`` returning the gateway's status for a key.
        call: ``(method, path, body=None)`` performing one admin request.
        consumer_key: a live consumer key that must survive the revocation.
        sleep: ``(seconds) -> None`` used while waiting for a revocation.
    """
    anonymous = get_status(None)
    if anonymous not in UNAUTHORIZED:
        raise ProbeError(
            f"the gateway answered an unauthenticated GET /v1/models with "
            f"{anonymous}; it is reachable without a key on the overlay"
        )

    forged = get_status("sk-" + "0" * 32)
    if forged not in UNAUTHORIZED:
        raise ProbeError(
            f"the gateway answered a forged bearer token with {forged}; it is "
            f"not validating keys"
        )

    with contextlib.suppress(urllib.error.HTTPError):
        call("POST", "/key/delete", {"key_aliases": [PROBE_ALIAS]})
    minted = call("POST", "/key/generate", {"key_alias": PROBE_ALIAS})["key"]
    accepted = get_status(minted)
    if accepted != 200:
        raise ProbeError(
            f"the gateway answered its own freshly minted virtual key with "
            f"{accepted}; virtual keys do not grant access"
        )

    call("POST", "/key/delete", {"keys": [minted]})
    revoked = await_rejection(get_status, minted, sleep)
    if revoked not in UNAUTHORIZED:
        raise ProbeError(
            f"the revoked probe key still answers with {revoked} after "
            f"{REVOCATION_ATTEMPTS * REVOCATION_DELAY}s; revocation does not "
            f"take effect"
        )

    survivor = get_status(consumer_key)
    if survivor != 200:
        raise ProbeError(
            f"revoking the probe key left a consumer key answering {survivor}; "
            f"revocation is not isolated to one consumer"
        )


def main():
    base = "http://127.0.0.1:" + os.environ["LITELLM_PORT"]
    probe(
        lambda key: status_of(base, key),
        admin_call(base, os.environ["LITELLM_MK"]),
        os.environ["LITELLM_KEY"],
    )
    print("AUTHENTICATED")


if __name__ == "__main__":
    main()

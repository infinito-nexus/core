"""Webhook intake rules for svc-ai-agent-orchestrator.

The orchestrator accepts a webhook only with a valid signature, drops a
repeated delivery id, and then re-fetches the event by id from the provider's
API and acts on the fetched data, never on the webhook body. This module holds
the deterministic, stack-free parts: the signature check and the delivery-id
deduplication. The re-fetch itself is an I/O step the orchestrator performs
against the provider; `refetch_required` states that it must happen.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def verify_signature(secret: bytes, body: bytes, header: str | None) -> bool:
    """Return whether ``header`` is a valid ``sha256=`` HMAC of ``body``.

    Mirrors the ``X-Hub-Signature-256`` scheme GitHub and Gitea use. The
    comparison is constant time; a missing or malformed header is invalid.

    Args:
        secret: the shared webhook secret.
        body: the exact request body bytes the signature covers.
        header: the signature header value, or ``None`` when absent.
    """
    if not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"{SIGNATURE_PREFIX}{digest}", header)


def refetch_required() -> bool:
    """The orchestrator always re-fetches the event by id and acts on the
    fetched data, never on the webhook body."""
    return True


class Deduplicator:
    """Drop a repeated webhook delivery id.

    The deployed orchestrator keeps the seen ids in Postgres; this in-memory
    implementation is the contract and the test double. ``seen`` returns True
    the first time it sees an id (accept) and False on a repeat (drop).
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, delivery_id: str) -> bool:
        if delivery_id in self._seen:
            return False
        self._seen.add(delivery_id)
        return True


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    secret = b"s3cr3t"
    body = b'{"action":"opened"}'
    good = f"{SIGNATURE_PREFIX}{hmac.new(secret, body, hashlib.sha256).hexdigest()}"
    _expect(verify_signature(secret, body, good), "valid signature rejected")
    _expect(not verify_signature(secret, body + b"x", good), "tampered body accepted")
    _expect(not verify_signature(b"wrong", body, good), "wrong secret accepted")
    _expect(not verify_signature(secret, body, None), "missing header accepted")
    _expect(not verify_signature(secret, body, "md5=deadbeef"), "wrong scheme accepted")
    dedup = Deduplicator()
    _expect(dedup.seen("d1") and not dedup.seen("d1"), "delivery id not deduplicated")
    _expect(dedup.seen("d2"), "distinct id dropped")
    _expect(refetch_required(), "refetch not required")
    print("orchestrator webhook self-check ok")


if __name__ == "__main__":
    _demo()

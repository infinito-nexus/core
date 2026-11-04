from __future__ import annotations

import base64
import binascii
import json

from ansible.errors import AnsibleFilterError
from cryptography.hazmat.primitives.asymmetric import ec

_SCALAR_BYTES = 32


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def atmo_client_assertion_jwk(private_scalar, kid) -> str:
    """Build the ES256 private JWK atmo signs its OAuth client assertions with.

    Args:
        private_scalar: unpadded base64url P-256 private scalar, the shape the
            ``vapid_private`` credential algorithm generates.
        kid: key id the worker publishes in ``/oauth/jwks.json``.

    Returns:
        Compact JSON with ``alg``, ``crv``, ``d``, ``kid``, ``kty``, ``x`` and
        ``y``; the public coordinates are derived from the scalar, so the key
        pair cannot drift apart.
    """
    if not isinstance(private_scalar, str) or not private_scalar.strip():
        raise AnsibleFilterError(
            "atmo_client_assertion_jwk: the private scalar is empty"
        )
    if not isinstance(kid, str) or not kid.strip():
        raise AnsibleFilterError("atmo_client_assertion_jwk: the key id is empty")
    try:
        raw = _b64url_decode(private_scalar.strip())
    except (binascii.Error, ValueError) as exc:
        raise AnsibleFilterError(
            "atmo_client_assertion_jwk: the private scalar is not base64url"
        ) from exc
    if len(raw) != _SCALAR_BYTES:
        raise AnsibleFilterError(
            f"atmo_client_assertion_jwk: the private scalar decodes to {len(raw)} bytes, "
            f"a P-256 scalar has {_SCALAR_BYTES}"
        )
    try:
        key = ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
    except ValueError as exc:
        raise AnsibleFilterError(
            "atmo_client_assertion_jwk: the private scalar is outside the P-256 group order"
        ) from exc
    public = key.public_key().public_numbers()
    return json.dumps(
        {
            "alg": "ES256",
            "crv": "P-256",
            "d": _b64url(raw),
            "kid": kid.strip(),
            "kty": "EC",
            "x": _b64url(public.x.to_bytes(_SCALAR_BYTES, "big")),
            "y": _b64url(public.y.to_bytes(_SCALAR_BYTES, "big")),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


class FilterModule:
    def filters(self):
        return {"atmo_client_assertion_jwk": atmo_client_assertion_jwk}

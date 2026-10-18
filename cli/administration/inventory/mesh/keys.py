from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

KEY_LENGTH = 32


def generate_private_key() -> str:
    raw = X25519PrivateKey.generate().private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    return base64.b64encode(raw).decode("ascii")


def public_key_of(private_key: str) -> str:
    raw = base64.b64decode(private_key, validate=True)
    if len(raw) != KEY_LENGTH:
        raise ValueError(
            f"private key decodes to {len(raw)} bytes, expected {KEY_LENGTH}"
        )
    return base64.b64encode(
        X25519PrivateKey.from_private_bytes(raw)
        .public_key()
        .public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    ).decode("ascii")


def is_valid_public_key(value: str) -> bool:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return False
    if len(raw) != KEY_LENGTH:
        return False
    try:
        X25519PublicKey.from_public_bytes(raw)
    except ValueError:
        return False
    return True

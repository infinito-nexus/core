"""Offline Tor v3 onion-service key minting.

Deterministically derives a Tor v3 hidden-service address and the exact
``HiddenServiceDir`` key files from an ed25519 seed, without running Tor.

The v3 address is ``base32(PUBKEY || CHECKSUM || VERSION)`` where
``CHECKSUM = SHA3-256(".onion checksum" || PUBKEY || VERSION)[:2]`` and
``VERSION = 0x03`` (see spec.torproject.org/address-spec). Tor stores the
*expanded* ed25519 secret key ``clamp(SHA512(seed)[:32]) || SHA512(seed)[32:]``
in ``hs_ed25519_secret_key``; the public key ``clamp(SHA512(seed)[:32]) * B``
equals the standard ed25519 public key, so it is taken straight from
``cryptography`` without needing scalar multiplication.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ONION_VERSION = b"\x03"
CHECKSUM_SALT = b".onion checksum"

# Tor key-file headers: 29 ASCII bytes padded with 3 NULs to a 32-byte header.
SECRET_KEY_HEADER = b"== ed25519v1-secret: type0 ==\x00\x00\x00"
PUBLIC_KEY_HEADER = b"== ed25519v1-public: type0 ==\x00\x00\x00"

SEED_LENGTH = 32


@dataclass(frozen=True)
class OnionKey:
    """A minted Tor v3 onion key and its ``HiddenServiceDir`` file contents."""

    seed: bytes
    address: str
    hostname: bytes
    public_key: bytes
    secret_key: bytes

    def files(self) -> dict[str, bytes]:
        """Map ``HiddenServiceDir`` filenames to their exact byte contents."""
        return {
            "hostname": self.hostname,
            "hs_ed25519_public_key": self.public_key,
            "hs_ed25519_secret_key": self.secret_key,
        }


def onion_address(public_key: bytes) -> str:
    """Return the v3 ``.onion`` address for a 32-byte ed25519 public key."""
    if len(public_key) != 32:
        raise ValueError(f"public key must be 32 bytes, got {len(public_key)}")
    checksum = hashlib.sha3_256(CHECKSUM_SALT + public_key + ONION_VERSION).digest()[:2]
    encoded = base64.b32encode(public_key + checksum + ONION_VERSION)
    return encoded.decode("ascii").lower() + ".onion"


def _expanded_secret_key(seed: bytes) -> bytes:
    """Return Tor's 64-byte expanded ed25519 secret key for ``seed``."""
    h = bytearray(hashlib.sha512(seed).digest())
    h[0] &= 248
    h[31] &= 127
    h[31] |= 64
    return bytes(h)


def mint(seed: bytes | None = None) -> OnionKey:
    """Mint a v3 onion key from ``seed`` (32 random bytes if omitted)."""
    if seed is None:
        seed = os.urandom(SEED_LENGTH)
    if len(seed) != SEED_LENGTH:
        raise ValueError(f"seed must be {SEED_LENGTH} bytes, got {len(seed)}")

    private = Ed25519PrivateKey.from_private_bytes(seed)
    public_bytes = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    address = onion_address(public_bytes)
    return OnionKey(
        seed=seed,
        address=address,
        hostname=(address + "\n").encode("ascii"),
        public_key=PUBLIC_KEY_HEADER + public_bytes,
        secret_key=SECRET_KEY_HEADER + _expanded_secret_key(seed),
    )


def mint_from_seed_b64(seed_b64: str) -> OnionKey:
    """Mint from a base64-encoded seed."""
    return mint(base64.b64decode(seed_b64))

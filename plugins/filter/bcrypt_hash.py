# Bcrypt hashing via the raw `bcrypt` package, bypassing Ansible's built-in
# `password_hash('bcrypt')` filter.
#
# `password_hash('bcrypt')` routes through passlib, whose bcrypt backend runs
# a self-test (`detect_wrap_bug`) against a fixed known-answer secret on
# first use. In environments where the installed `bcrypt` package and
# passlib's bundled version-detection drift apart (`bcrypt` has no
# `__about__.__version__` attribute passlib expects), that self-test itself
# raises "password cannot be longer than 72 bytes" — a misleading error
# unrelated to the caller's actual input, and one that makes the filter
# unusable for ANY input, not just long ones. The raw `bcrypt` package has no
# such self-test and hashes correctly in the same environment.
from __future__ import annotations

import base64
import hashlib

import bcrypt

_STD_TO_BCRYPT_B64 = bytes.maketrans(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
    b"./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
)


def _seeded_salt(seed: str, secret: bytes) -> bytes:
    """A fixed bcrypt salt derived from the seed and the secret.

    Args:
        seed: caller-chosen, non-empty string that separates otherwise equal secrets.
        secret: the UTF-8 encoded secret being hashed.

    Returns:
        ``$2b$12$`` plus 22 bcrypt-base64 characters encoding the first 16
        bytes of sha256(seed + secret).
    """
    digest = hashlib.sha256(seed.encode("utf-8") + secret).digest()[:16]
    encoded = base64.b64encode(digest)[:22].translate(_STD_TO_BCRYPT_B64)
    return b"$2b$12$" + encoded


class FilterModule:
    def filters(self):
        return {
            "bcrypt_hash": self.bcrypt_hash,
        }

    @staticmethod
    def bcrypt_hash(value, salt_seed=None):
        if not isinstance(value, str) or not value:
            raise ValueError("bcrypt_hash: value must be a non-empty string")

        secret = value.encode("utf-8")
        if len(secret) > 72:
            raise ValueError(
                f"bcrypt_hash: secret is {len(secret)} bytes in UTF-8; bcrypt "
                "accepts at most 72 bytes. Shorten the secret instead of "
                "letting bcrypt truncate or reject it."
            )

        if salt_seed is None:
            salt = bcrypt.gensalt()
        elif isinstance(salt_seed, str) and salt_seed:
            salt = _seeded_salt(salt_seed, secret)
        else:
            raise ValueError("bcrypt_hash: salt_seed must be a non-empty string when given")

        return bcrypt.hashpw(secret, salt).decode("utf-8")

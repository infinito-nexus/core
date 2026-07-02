import base64
import hashlib
import re
import secrets
import string

import bcrypt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


class ValueGenerator:
    PASSWORD_REGEX = re.compile(
        r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$"
    )

    def __init__(self) -> None:
        self._vapid_keypair: tuple[str, str] | None = None

    def generate_strong_password(self, length: int = 32) -> str:
        if length < 12:
            raise ValueError("Password length must be at least 12 characters")

        characters = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]:,.?"

        for _ in range(10_000):
            password = "".join(secrets.choice(characters) for _ in range(length))
            if self._is_valid_password(password):
                return password

        raise RuntimeError("Failed to generate a valid password after many attempts")

    def _is_valid_password(self, password: str) -> bool:
        return bool(self.PASSWORD_REGEX.match(password))

    def generate_secure_alphanumeric(self, length: int) -> str:
        """Generate a cryptographically secure random alphanumeric string of the given length."""
        characters = string.ascii_letters + string.digits
        return "".join(secrets.choice(characters) for _ in range(length))

    def generate_vapid_keypair(self) -> tuple[str, str]:
        """Return a linked (private, public) VAPID keypair, cached per instance.

        Returns:
            A tuple of unpadded base64url strings: the P-256 private scalar
            (32 bytes) and the uncompressed public point (65 bytes, 0x04||X||Y),
            in the format the Web Push / mastodon ecosystem expects.
        """
        if self._vapid_keypair is None:
            private_key = ec.generate_private_key(ec.SECP256R1())
            scalar = private_key.private_numbers().private_value.to_bytes(32, "big")
            point = private_key.public_key().public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            )
            self._vapid_keypair = (
                base64.urlsafe_b64encode(scalar).rstrip(b"=").decode(),
                base64.urlsafe_b64encode(point).rstrip(b"=").decode(),
            )
        return self._vapid_keypair

    def generate_value(self, algorithm: str) -> str:
        """
        Generate a random secret value according to the specified algorithm.

        Supported algorithms:
        • "random_hex"
        • "random_hex_32"
        • "random_hex_16"
        • "sha256"
        • "sha1"
        • "strong_password"
        • "bcrypt"
        • "alphanumeric"
        • "base64_prefixed_32"
        • "vapid_private"
        • "vapid_public"
        """
        if algorithm == "random_hex":
            return secrets.token_hex(64)
        if algorithm == "random_hex_32":
            return secrets.token_hex(32)
        if algorithm == "random_hex_16":
            return secrets.token_hex(16)
        if algorithm == "sha256":
            return hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        if algorithm == "sha1":
            return hashlib.sha1(
                secrets.token_bytes(20),
                usedforsecurity=False,
            ).hexdigest()
        if algorithm == "strong_password":
            return self.generate_strong_password(32)
        if algorithm == "bcrypt":
            pw = secrets.token_urlsafe(16).encode()
            raw_hash = bcrypt.hashpw(pw, bcrypt.gensalt()).decode()
            alnum = string.digits + string.ascii_lowercase
            return "".join(
                secrets.choice(alnum) if ch == "$" else ch for ch in raw_hash
            )
        if algorithm == "alphanumeric":
            return self.generate_secure_alphanumeric(64)
        if algorithm == "base64_prefixed_32":
            return "base64:" + base64.b64encode(secrets.token_bytes(32)).decode()
        if algorithm == "vapid_private":
            return self.generate_vapid_keypair()[0]
        if algorithm == "vapid_public":
            return self.generate_vapid_keypair()[1]
        return "undefined"

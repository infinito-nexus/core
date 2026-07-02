import base64
import hashlib
import re
import secrets
import string

import bcrypt


class ValueGenerator:
    # Password policy:
    # - min 12 chars
    # - at least one lowercase
    # - at least one uppercase
    # - at least one digit
    # - at least one special char
    PASSWORD_REGEX = re.compile(
        r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$"
    )

    def generate_strong_password(self, length: int = 32) -> str:
        if length < 12:
            raise ValueError("Password length must be at least 12 characters")

        # Exclude '{' and '}' so secrets can't form Jinja delimiters (values get re-rendered).
        characters = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]:,.?"

        for _ in range(10_000):  # defensive upper bound
            password = "".join(secrets.choice(characters) for _ in range(length))
            if self._is_valid_password(password):
                return password

        raise RuntimeError("Failed to generate a valid password after many attempts")

    def _is_valid_password(self, password: str) -> bool:
        return bool(self.PASSWORD_REGEX.match(password))

    def generate_secure_alphanumeric(self, length: int) -> str:
        """Generate a cryptographically secure random alphanumeric string of the given length."""
        characters = string.ascii_letters + string.digits  # a-zA-Z0-9
        return "".join(secrets.choice(characters) for _ in range(length))

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
            # SHA-1 is selected by the caller for legacy app compatibility;
            # the input is fresh random bytes, not security-sensitive data.
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
        return "undefined"

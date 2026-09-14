from __future__ import annotations

import re
import secrets
import string

from utils.manager.value_generator import ValueGenerator

USER_PASSWORD_LENGTH = 64
DECLARED_PASSWORD_ATTEMPTS = 64
SHELL_SAFE_MARKS = "-_."
_USER_PASSWORD_ALPHABET = string.ascii_letters + string.digits + SHELL_SAFE_MARKS
_USER_PASSWORD_RE = re.compile(
    r"^[A-Za-z0-9](?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[-_.])[A-Za-z0-9._-]{15,}$"
)


def generate_random_password(length: int = 64) -> str:
    return ValueGenerator().generate_strong_password(length)


def generate_user_password(length: int = USER_PASSWORD_LENGTH) -> str:
    """Return a shell-safe password for a declared user.

    Args:
        length: characters to generate, at least 16.

    Returns:
        letters, digits and the marks ``-_.``, never a leading ``-``, with one
        of each class the Keycloak realm policy ``specialChars(1)`` counts.
    """
    if length < 16:
        raise ValueError("A user password must be at least 16 characters")
    for _ in range(DECLARED_PASSWORD_ATTEMPTS):
        body = [secrets.choice(_USER_PASSWORD_ALPHABET) for _ in range(length)]
        body[0] = secrets.choice(string.ascii_letters + string.digits)
        body[secrets.randbelow(length - 1) + 1] = secrets.choice(SHELL_SAFE_MARKS)
        password = "".join(body)
        if _USER_PASSWORD_RE.match(password):
            return password
    raise RuntimeError("Failed to generate a user password after many attempts")


def generate_declared_user_password(username, algorithm, validation):
    """Return a password satisfying what the user's own declaration demands.

    Args:
        username: the user the password belongs to, for the failure message.
        algorithm: a ValueGenerator algorithm name, or None for the shell-safe
            default every user gets when its declaration asks for nothing.
        validation: a regular expression the value must match, or None.

    An application whose registration rejects the shell-safe alphabet states
    that in its own meta/users.yml rather than carrying a second credential
    beside the account it already owns.
    """
    for _ in range(DECLARED_PASSWORD_ATTEMPTS):
        value = (
            ValueGenerator().generate_value(algorithm)
            if algorithm
            else generate_user_password()
        )
        if not validation or re.search(validation, value):
            return value
    raise SystemExit(
        f"user {username!r}: {DECLARED_PASSWORD_ATTEMPTS} passwords from "
        f"algorithm {algorithm or 'the shell-safe default'!r} all failed "
        f"password_validation {validation!r}; the two cannot both hold"
    )

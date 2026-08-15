from __future__ import annotations

import re

from utils.manager.value_generator import ValueGenerator

USER_PASSWORD_LENGTH = 64
DECLARED_PASSWORD_ATTEMPTS = 64


def generate_random_password(length: int = 64) -> str:
    return ValueGenerator().generate_strong_password(length)


def generate_user_password(length: int = USER_PASSWORD_LENGTH) -> str:
    """Return a shell-safe password for a declared user.

    Args:
        length: characters to generate.

    A user password reaches its application through Ansible, a shell, a
    ``container exec -e`` and finally the runtime's own environment reader. The
    punctuation in ``generate_strong_password`` does not survive that chain
    intact, which is why roles used to declare a separate alphanumeric
    credential rather than use the user's own password. At this length the
    alphabet costs nothing worth measuring.
    """
    return ValueGenerator().generate_secure_alphanumeric(length)


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

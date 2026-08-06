from __future__ import annotations

from utils.manager.value_generator import ValueGenerator

USER_PASSWORD_LENGTH = 64


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

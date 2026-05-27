from __future__ import annotations

import secrets
import string


def generate_random_password(length: int = 64) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

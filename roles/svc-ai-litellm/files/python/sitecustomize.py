"""Admit the platform's own e-mail TLD to email-validator inside the gateway.

Exception: LiteLLM builds the SSO identity as fastapi-sso's ``OpenID``, whose
``email`` is a pydantic ``EmailStr``. email-validator rejects every address on
a special-use TLD such as ``test``, so on a platform served under one each SSO
callback dies with a ``ValidationError`` and a bare 500 before the group check.
``SPECIAL_USE_DOMAIN_NAMES`` is part of email-validator's public API for this.
Python imports this module at interpreter start because the gateway's
``PYTHONPATH`` names the directory it is mounted in.

Environment:
    LITELLM_EMAIL_TLD: TLD of the platform's user addresses; unset disables it.
"""

from __future__ import annotations

import os


def admit(tld: str) -> None:
    """Drop one TLD from email-validator's special-use rejection list.

    Args:
        tld: the TLD to admit; empty admits nothing.
    """
    if not tld:
        return
    import email_validator

    email_validator.SPECIAL_USE_DOMAIN_NAMES[:] = [
        name for name in email_validator.SPECIAL_USE_DOMAIN_NAMES if name != tld
    ]


admit(os.environ.get("LITELLM_EMAIL_TLD", "").strip().lower())

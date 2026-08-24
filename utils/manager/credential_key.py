"""The one accepted ``--set`` key shape for a credential override.

Both the CLI that parses ``--set`` and the inventory manager that consumes the
parsed pairs build the key here, so a credential is addressed by exactly one
string. A short form would name different credentials on different apps.
"""

from __future__ import annotations

OVERRIDE_ROOT = "applications"
SECRETS_KEY = "secrets"
CREDENTIALS_KEY = "credentials"
OVERRIDE_SECTION = f"{SECRETS_KEY}.{CREDENTIALS_KEY}"


def override_key(app_id: str, key: str) -> str:
    """Build the override key for one credential.

    Args:
        app_id: application the credential belongs to.
        key: dotted path inside the schema's ``credentials`` node, e.g.
            ``recaptcha.secret``.
    """
    return f"{OVERRIDE_ROOT}.{app_id}.{OVERRIDE_SECTION}.{key}"


def split_override_key(key: str) -> tuple[str, str]:
    """Split an override key back into ``(app_id, credential path)``.

    Args:
        key: a key in the shape :func:`override_key` builds.
    """
    app_id, credential = key[len(OVERRIDE_ROOT) + 1 :].split(f".{OVERRIDE_SECTION}.", 1)
    return app_id, credential

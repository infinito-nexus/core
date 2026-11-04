"""Derive the OpenSSH public key line of an OpenSSH private key.

{{ lookup('config', 'web-app-semaphore', 'secrets.credentials.app_control_ssh_key') | ssh_public_key }}
->  ssh-ed25519 AAAA...
"""

from __future__ import annotations

from ansible.errors import AnsibleFilterError
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_ssh_private_key,
)


def ssh_public_key(private_key) -> str:
    """Return the ``authorized_keys`` form of the public half of ``private_key``.

    Args:
        private_key: an unencrypted key in the ``OPENSSH PRIVATE KEY`` format.
    """
    try:
        key = load_ssh_private_key(str(private_key).encode("utf-8"), password=None)
    except (ValueError, TypeError) as error:
        raise AnsibleFilterError(
            "ssh_public_key: the value is no unencrypted OpenSSH private key"
        ) from error
    public = key.public_key()
    return public.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()


class FilterModule:
    def filters(self):
        return {"ssh_public_key": ssh_public_key}

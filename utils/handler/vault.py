from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any

import yaml
from yaml.dumper import SafeDumper
from yaml.loader import SafeLoader

if TYPE_CHECKING:
    from ansible.parsing.vault import VaultLib


class VaultScalar(str):
    """A subclass of str to represent vault-encrypted strings."""

    __slots__ = ()


def _vault_constructor(loader, node):
    """Load a !vault block as a VaultScalar so the tag survives a round-trip."""
    return VaultScalar(node.value)


def _vault_representer(dumper, data):
    """Custom representer to dump VaultScalar as literal blocks."""
    return dumper.represent_scalar("!vault", data, style="|")


SafeLoader.add_constructor("!vault", _vault_constructor)
getattr(yaml, "CSafeLoader", SafeLoader).add_constructor("!vault", _vault_constructor)
SafeDumper.add_representer(VaultScalar, _vault_representer)


class VaultHandler:
    def __init__(self, vault_password_file: str):
        self.vault_password_file = vault_password_file

    @cached_property
    def _vault(self) -> VaultLib:
        from ansible.parsing.dataloader import DataLoader
        from ansible.parsing.vault import FileVaultSecret, VaultLib

        secret = FileVaultSecret(filename=self.vault_password_file, loader=DataLoader())
        secret.load()
        return VaultLib([("default", secret)])

    def encrypt_string(self, value: str, name: str) -> str:
        """Return the ``name: !vault |`` snippet as ``ansible-vault`` lays it out.

        Args:
            value: plaintext to encrypt.
            name: key the snippet is emitted under.
        """
        body = self._vault.encrypt(value).decode()
        indented = "\n".join(f"          {line}" for line in body.splitlines())
        return f"{name}: !vault |\n{indented}\n"

    def encrypt_leaves(self, branch: dict[str, Any], vault_pw: str):
        """Recursively encrypt all leaves (plain text values) under the credentials section."""
        for key, value in branch.items():
            if isinstance(value, dict):
                self.encrypt_leaves(value, vault_pw)
            elif isinstance(value, str) and not value.lstrip().startswith(
                "$ANSIBLE_VAULT"
            ):
                snippet = self.encrypt_string(value, key)
                lines = snippet.splitlines()
                indent = len(lines[1]) - len(lines[1].lstrip())
                body = "\n".join(line[indent:] for line in lines[1:])
                branch[key] = VaultScalar(body)

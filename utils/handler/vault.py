import subprocess
from typing import Any

from yaml.dumper import SafeDumper
from yaml.loader import SafeLoader


class VaultScalar(str):
    """A subclass of str to represent vault-encrypted strings."""

    __slots__ = ()


def _vault_constructor(loader, node):
    """Custom constructor to handle !vault tag as plain text."""
    return node.value


def _vault_representer(dumper, data):
    """Custom representer to dump VaultScalar as literal blocks."""
    return dumper.represent_scalar("!vault", data, style="|")


SafeLoader.add_constructor("!vault", _vault_constructor)
SafeDumper.add_representer(VaultScalar, _vault_representer)


class VaultHandler:
    def __init__(self, vault_password_file: str):
        self.vault_password_file = vault_password_file

    def encrypt_string(self, value: str, name: str) -> str:
        """Encrypt a string using ansible-vault."""
        cmd = [
            "ansible-vault",
            "encrypt_string",
            "--stdin-name",
            name,
            "--vault-password-file",
            self.vault_password_file,
        ]
        proc = subprocess.run(
            cmd, input=value, capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ansible-vault encrypt_string failed:\n{proc.stderr}")
        return proc.stdout

    def encrypt_leaves(self, branch: dict[str, Any], vault_pw: str):
        """Recursively encrypt all leaves (plain text values) under the credentials section."""
        for key, value in branch.items():
            if isinstance(value, dict):
                self.encrypt_leaves(value, vault_pw)  # Recurse into nested dictionaries
            # Skip if already vaulted (i.e., starts with $ANSIBLE_VAULT)
            elif isinstance(value, str) and not value.lstrip().startswith(
                "$ANSIBLE_VAULT"
            ):
                snippet = self.encrypt_string(value, key)
                lines = snippet.splitlines()
                indent = len(lines[1]) - len(lines[1].lstrip())
                body = "\n".join(line[indent:] for line in lines[1:])
                branch[key] = VaultScalar(body)  # Store encrypted value as VaultScalar

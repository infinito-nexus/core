import argparse
from pathlib import Path
import yaml
from typing import Any
from utils.handler.vault import VaultHandler, VaultScalar
from utils.handler.yaml import YamlHandler
from yaml.dumper import SafeDumper


def ask_for_confirmation(key: str) -> bool:
    """Prompt the user for confirmation to overwrite an existing value."""
    confirmation = (
        input(f"Do you want to encrypt the value for '{key}'? (y/n): ").strip().lower()
    )
    return confirmation == "y"


def encrypt_recursively(
    data: Any,
    vault_handler: VaultHandler,
    ask_confirmation: bool = True,
    prefix: str = "",
) -> Any:
    """Recursively encrypt values in the data."""
    if isinstance(data, dict):
        for key, value in data.items():
            new_prefix = f"{prefix}.{key}" if prefix else key
            data[key] = encrypt_recursively(
                value, vault_handler, ask_confirmation, new_prefix
            )
    elif isinstance(data, list):
        for i, item in enumerate(data):
            data[i] = encrypt_recursively(item, vault_handler, ask_confirmation, prefix)
    elif isinstance(data, str):
        # Only encrypt if it's not already vaulted
        if not data.lstrip().startswith("$ANSIBLE_VAULT"):
            if ask_confirmation:
                # Ask for confirmation before encrypting if not `--all`
                if not ask_for_confirmation(prefix):
                    print(f"Skipping encryption for '{prefix}'.")
                    return data
            encrypted_value = vault_handler.encrypt_string(data, prefix)
            lines = encrypted_value.splitlines()
            indent = len(lines[1]) - len(lines[1].lstrip())
            body = "\n".join(line[indent:] for line in lines[1:])
            return VaultScalar(body)  # Store encrypted value as VaultScalar
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt all fields, ask for confirmation unless --all is specified."
    )
    parser.add_argument(
        "--inventory-file", required=True, help="Host vars file to update"
    )
    parser.add_argument(
        "--vault-password-file", required=True, help="Vault password file"
    )
    parser.add_argument(
        "--all", action="store_true", help="Encrypt all fields without confirmation"
    )
    args = parser.parse_args()

    # Initialize the VaultHandler and load the inventory
    vault_handler = VaultHandler(vault_password_file=args.vault_password_file)
    updated_inventory = YamlHandler.load_yaml(Path(args.inventory_file))

    # 1) Encrypt all fields recursively
    updated_inventory = encrypt_recursively(
        updated_inventory, vault_handler, ask_confirmation=not args.all
    )

    # 2) Save the updated inventory to file. The custom SafeDumper
    # subclass emits !vault literal blocks; the cached dump_yaml writes
    # plain YAML which is the wrong output here.
    with open(args.inventory_file, "w", encoding="utf-8") as f:
        yaml.dump(  # noqa: direct-yaml
            updated_inventory, f, sort_keys=False, Dumper=SafeDumper
        )

    print(f"✅ Inventory selectively vaulted → {args.inventory_file}")


if __name__ == "__main__":
    main()

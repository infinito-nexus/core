"""Round-trip YAML access for the inventory files this package rewrites.

The counterpart to :mod:`yaml_io`, which reads values. Everything here keeps
comments, quoting and vault tags intact, because host_vars is hand-edited as
often as it is generated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from utils.handler.vault import VaultHandler

if TYPE_CHECKING:
    from pathlib import Path


def round_trip_yaml() -> YAML:
    """Return a YAML handler configured the way every writer here needs it."""
    handler = YAML(typ="rt")
    handler.preserve_quotes = True
    return handler


def as_commented_map(data: Any) -> CommentedMap:
    """Return ``data`` as a CommentedMap, empty when it holds no mapping.

    Args:
        data: whatever a round-trip load returned.
    """
    if isinstance(data, CommentedMap):
        return data
    if data is None:
        return CommentedMap()
    migrated = CommentedMap()
    for key, value in dict(data).items():
        migrated[key] = value
    return migrated


def load_document(path: Path) -> CommentedMap:
    """Return the round-trip document at ``path``, empty when it does not exist.

    Args:
        path: the YAML file to read.
    """
    if not path.exists():
        return CommentedMap()
    with path.open("r", encoding="utf-8") as handle:
        return as_commented_map(round_trip_yaml().load(handle))


def dump_document(path: Path, document: CommentedMap) -> None:
    """Write ``document`` to ``path``, creating the parent directory.

    Args:
        path: the YAML file to write.
        document: the round-trip document to serialise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        round_trip_yaml().dump(document, handle)


def ensure_map(node: CommentedMap, key: str) -> CommentedMap:
    """Return ``node[key]`` as a CommentedMap, creating it when absent.

    Args:
        node: the parent mapping.
        key: the child key to resolve.
    """
    if key not in node or not isinstance(node.get(key), CommentedMap):
        node[key] = CommentedMap()
    return node[key]


def vault_value(vault_password_file: Path | str, plain: str, name: str) -> Any:
    """Return ``plain`` as a parsed ``!vault`` node ready to assign.

    Args:
        vault_password_file: vault password used to encrypt.
        plain: the secret to encrypt.
        name: the key ansible-vault names the snippet after.

    ansible-vault emits a YAML snippet rather than a value, so the encrypted
    node has to be read back out of it before it can be assigned anywhere.
    """
    snippet = VaultHandler(str(vault_password_file)).encrypt_string(plain, name)
    encrypted = as_commented_map(round_trip_yaml().load(snippet)).get(name)
    if encrypted is None:
        raise SystemExit(f"Failed to parse {name!r} from ansible-vault output.")
    return encrypted

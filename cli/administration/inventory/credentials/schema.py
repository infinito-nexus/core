from __future__ import annotations

import functools
import os
import re
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cli.administration.inventory.provision.users_generator import (
    required_user_policies,
)
from utils.manager.value_generator import ValueGenerator
from utils.openbao_client import REFERENCE_KEY

from .emit import declared_credentials
from .openbao import FIELD, ReferenceInventoryManager

PLAIN = "plain"
DEFAULT = "default"
UNDEFINED = "undefined"
TEMPLATE = re.compile(r"\{\{.*\}\}", re.DOTALL)
MARKER = re.compile(r"\{\{ (?P<nonce>[0-9a-f]{16}):(?P<algorithm>[A-Za-z0-9_]+) \}\}")
USERS_FOLDER = "users"
USER_FIELD = "password"


@functools.cache
def _kind(algorithm: str) -> str:
    """Args:
    algorithm: a generator kind a schema names.

    Returns:
        The kind, or ``UNDEFINED`` for one ``ValueGenerator`` does not know
        and therefore writes as the text ``undefined``.
    """
    known = ValueGenerator().generate_value(algorithm) != UNDEFINED
    return algorithm if known else UNDEFINED


class AlgorithmRecorder:
    def __init__(self) -> None:
        self.nonce = secrets.token_hex(8)

    def generate_value(self, algorithm: str) -> str:
        """Args:
        algorithm: the generator kind the schema asks for.

        Returns:
            A template marker naming the kind under this recorder's nonce,
            never a value; the supplied-value checks of the schema skip it.
        """
        return f"{{{{ {self.nonce}:{_kind(algorithm)} }}}}"

    def algorithm(self, value: Any) -> str | None:
        """Args:
        value: a credential value the schema produced.

        Returns:
            The kind of a marker of ``generate_value``, None for any other value.
        """
        found = MARKER.fullmatch(value) if isinstance(value, str) else None
        if found is None or found["nonce"] != self.nonce:
            return None
        return found["algorithm"]


class SchemaInventoryManager(ReferenceInventoryManager):
    def __init__(self, role_path: Path) -> None:
        """Args:
        role_path: the role whose credentials, shared providers included,
            ``infinito inventory credentials --openbao --allow-empty-plain``
            would write.
        """
        super().__init__(
            role_path=role_path,
            inventory_path=Path(os.devnull),
            vault_pw="",
            overrides={},
            allow_empty_plain=True,
        )
        self.value_generator = AlgorithmRecorder()


def _entries(
    node: Mapping[str, Any],
    app_id: str,
    key_path: str,
    recorder: AlgorithmRecorder,
) -> list[dict]:
    found: list[dict] = []
    for key, value in node.items():
        full_key = f"{key_path}.{key}" if key_path else str(key)
        if isinstance(value, Mapping) and REFERENCE_KEY not in value:
            found.extend(_entries(value, app_id, full_key, recorder))
            continue
        entry = {
            "application": app_id,
            "key": full_key,
            "path": f"{app_id}/{full_key.replace('.', '/')}",
            "field": FIELD,
        }
        algorithm = recorder.algorithm(value)
        if algorithm is not None:
            entry["algorithm"] = algorithm
        elif value in (None, ""):
            entry["algorithm"] = PLAIN
        elif isinstance(value, str) and TEMPLATE.fullmatch(value):
            entry.update(algorithm=DEFAULT, default=value)
        else:
            raise ValueError(
                f"{app_id}.{full_key} holds neither a generator kind nor a template default"
            )
        found.append(entry)
    return found


def credential_schema(
    roles_dir: Path, application_ids: list[str]
) -> dict[str, list[dict]]:
    """Args:
    roles_dir: the roles directory of the core tree.
    application_ids: the applications a workspace deploys.

    Returns:
        ``credentials``: per generated credential its ``application``,
        dotted ``key``, KV ``path`` below the workspace prefix, ``field`` and
        generator ``algorithm`` (``plain`` stays an empty string, ``default``
        carries the role's template ``default``), exactly as the reference
        mode of ``infinito inventory credentials`` writes them;
        ``users``: per user the deploy needs a password for its ``name``,
        ``path``, ``field``, ``algorithm`` and ``validation``. No value.
        Entries the applications share appear once.
    """
    credentials: dict[str, dict] = {}
    for application_id in application_ids:
        role_path = roles_dir / application_id
        if not role_path.is_dir():
            raise ValueError(f"{application_id} is no role of {roles_dir}")
        manager = SchemaInventoryManager(role_path)
        applications = manager.apply_schema().get("applications") or {}
        for app_id, block in sorted(applications.items()):
            if not isinstance(block, Mapping):
                continue
            declared = declared_credentials(block) or {}
            for entry in _entries(declared, app_id, "", manager.value_generator):
                if credentials.setdefault(entry["path"], entry) != entry:
                    raise ValueError(
                        f"{entry['path']} is generated two ways for {application_ids}"
                    )
    users = [
        {
            "name": name,
            "path": f"{USERS_FOLDER}/{name}/{USER_FIELD}",
            "field": FIELD,
            "algorithm": _kind(policy["algorithm"]) if policy["algorithm"] else None,
            "validation": policy["validation"],
        }
        for name, policy in required_user_policies(
            roles_dir, list(application_ids)
        ).items()
    ]
    return {
        "credentials": sorted(credentials.values(), key=lambda e: e["path"]),
        "users": users,
    }

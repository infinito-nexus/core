from __future__ import annotations

import unittest
from collections.abc import Iterator, Mapping
from typing import Any

from utils.cache.yaml import load_yaml_any
from utils.openbao_client import REFERENCE_KEY
from utils.roles.mapping import ROLE_FILE_META_SECRETS

from . import PROJECT_ROOT


def named_openbao(node: Any, path: str) -> Iterator[str]:
    """
    Args:
        node: a ``credentials`` branch of a role's ``meta/secrets.yml``.
        path: the dotted name of that branch.

    Returns:
        The dotted name of every credential below it named ``openbao``.
    """
    if not isinstance(node, Mapping):
        return
    for key, value in node.items():
        name = f"{path}.{key}"
        if key == REFERENCE_KEY:
            yield name
        yield from named_openbao(value, name)


def offenders(roles_dir: Any) -> list[str]:
    found = []
    for secrets in sorted(roles_dir.glob(f"*/{ROLE_FILE_META_SECRETS}")):
        schema = load_yaml_any(str(secrets), default_if_missing=None) or {}
        credentials = schema.get("credentials") if isinstance(schema, Mapping) else None
        role = secrets.relative_to(roles_dir).parts[0]
        found.extend(
            f"roles/{role}/{ROLE_FILE_META_SECRETS}: {name}"
            for name in named_openbao(credentials, "credentials")
        )
    return found


class TestOpenBaoReferenceName(unittest.TestCase):
    def test_no_credential_is_named_openbao(self) -> None:
        self.assertEqual(offenders(PROJECT_ROOT / "roles"), [])

    def test_control_a_nested_credential_named_openbao_is_found(self) -> None:
        schema = {"recaptcha": {"openbao": {"algorithm": "alphanumeric"}}}
        self.assertEqual(
            list(named_openbao(schema, "credentials")),
            ["credentials.recaptcha.openbao"],
        )


if __name__ == "__main__":
    unittest.main()

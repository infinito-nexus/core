"""Lint: an adapter sidecar is started with the bearer its role declares.

Such a provider holds two unrelated credentials: the token the sidecar presents
upstream, read with ``lookup('mcp_credential', ...)``, and the bearer a client
must present to the sidecar, which ``mcp.credential`` declares under the role's
own ``credentials``. Starting the sidecar with anything else leaves a deployment
where the declared credential is the one every client is handed and the one the
endpoint answers 401 to.

The rule ties two sites to one variable: the ``vars/main.yml`` definition that
reads the declared credential key, and the ``ADAPTER_BEARER`` the sidecar is
started with.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-adapter-bearer`` in the head of the role's ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-adapter-bearer"
_ADAPTER_ENV = "ADAPTER_BEARER"


def _adapter_roles() -> list[tuple[Path, str]]:
    """Return the adapter-fronted roles and the credential key each declares."""
    roles: list[tuple[Path, str]] = []
    for mcp_path in sorted(Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        if str(mcp.get("implementation") or "").strip() != "adapter":
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        credential = mcp.get("credential")
        credential = credential if isinstance(credential, Mapping) else {}
        roles.append((mcp_path.parent.parent, str(credential.get("key") or "").strip()))
    return roles


def _variables_reading(role: Path, credential_key: str) -> set[str]:
    """Return the vars/main.yml names defined from that declared credential."""
    path = Path(role, "vars", "main.yml")
    if not path.is_file():
        return set()
    needle = f"credentials.{credential_key}"
    return {
        line.split(":", 1)[0].strip()
        for line in read_text(str(path)).splitlines()
        if needle in line and ":" in line and not line.startswith((" ", "#"))
    }


def _starts_sidecar_with(role: Path, variables: set[str]) -> bool:
    """Return whether a template starts the sidecar with one of those names."""
    return any(
        variable in line
        for template in sorted(role.glob("templates/**/*.j2"))
        for line in read_text(str(template)).splitlines()
        if _ADAPTER_ENV in line
        for variable in variables
    )


class TestMcpAdapterBearer(unittest.TestCase):
    def test_every_adapter_sidecar_serves_the_declared_bearer(self) -> None:
        offenders: list[str] = []
        for role, credential_key in _adapter_roles():
            if not credential_key:
                offenders.append(
                    f"{role.name}: fronts its MCP endpoint with an adapter but "
                    f"its mcp.credential names no key, so nothing states which "
                    f"secret a client presents"
                )
                continue
            variables = _variables_reading(role, credential_key)
            if not variables:
                offenders.append(
                    f"{role.name}: no vars/main.yml entry reads "
                    f"credentials.{credential_key}, the credential its mcp block "
                    f"declares"
                )
                continue
            if not _starts_sidecar_with(role, variables):
                offenders.append(
                    f"{role.name}: starts its sidecar with an {_ADAPTER_ENV} that "
                    f"is none of {sorted(variables)}, so the endpoint answers a "
                    f"different bearer than the one it declares"
                )
        self.assertEqual(
            [],
            offenders,
            f"MCP adapter provider(s) serving the wrong credential "
            f"({len(offenders)}):\n" + "\n".join(f"  - {o}" for o in offenders),
        )

    def test_the_scan_finds_adapter_providers(self) -> None:
        self.assertTrue(
            _adapter_roles(),
            "no MCP block declares an adapter implementation, so the rule would "
            "pass vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()

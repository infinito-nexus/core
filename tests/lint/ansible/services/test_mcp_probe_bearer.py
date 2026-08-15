"""Lint: an adapter-fronted provider probes the gateway with the gateway's bearer.

Such a provider holds two unrelated credentials: the token the sidecar presents
upstream, read with ``lookup('mcp_credential', ...)``, and the bearer a client
must present to the sidecar, generated from the role's ``credentials.mcp_bearer``.
Handing the upstream token to ``probe.yml`` produces a deploy that dies at the
contract probe with a 401 the log attributes to the adapter, not to the caller.

The rule ties the three sites to one variable: the probe include, the
``vars/main.yml`` definition that reads ``credentials.mcp_bearer``, and the
``ADAPTER_BEARER`` the sidecar is started with.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-probe-bearer`` in the head of the role's ``meta/mcp.yml``.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-probe-bearer"
_ASSIGNMENT = re.compile(r"mcp_probe_bearer:\s*\"?\{\{\s*([A-Za-z0-9_]+)\s*\}\}\"?")
_CREDENTIAL_KEY = "credentials.mcp_bearer"
_ADAPTER_ENV = "ADAPTER_BEARER"


def _adapter_roles() -> list[Path]:
    """Return the role directories whose MCP endpoint is an adapter sidecar."""
    roles: list[Path] = []
    for mcp_path in sorted(Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        if str(mcp.get("implementation") or "").strip() != "adapter":
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        roles.append(mcp_path.parent.parent)
    return roles


def _probe_bearer_variable(role: Path) -> str | None:
    """Return the variable name the role hands to the contract probe."""
    for task in sorted(role.glob("tasks/**/*.yml")):
        match = _ASSIGNMENT.search(read_text(str(task)))
        if match:
            return match.group(1)
    return None


def _defines_gateway_bearer(role: Path, variable: str) -> bool:
    """Return whether vars/main.yml reads that variable from the role's schema."""
    path = Path(role, "vars", "main.yml")
    if not path.is_file():
        return False
    for line in read_text(str(path)).splitlines():
        if line.startswith(f"{variable}:") and _CREDENTIAL_KEY in line:
            return True
    return False


def _starts_sidecar_with(role: Path, variable: str) -> bool:
    """Return whether a template starts the sidecar with that same variable."""
    return any(
        variable in line
        for template in sorted(role.glob("templates/**/*.j2"))
        for line in read_text(str(template)).splitlines()
        if _ADAPTER_ENV in line
    )


class TestMcpProbeBearer(unittest.TestCase):
    def test_every_adapter_provider_probes_with_its_gateway_bearer(self) -> None:
        offenders: list[str] = []
        for role in _adapter_roles():
            variable = _probe_bearer_variable(role)
            if variable is None:
                offenders.append(
                    f"{role.name}: fronts its MCP endpoint with an adapter but "
                    f"hands mcp_probe_bearer no plain variable, so the probe may "
                    f"present the upstream token the sidecar rejects"
                )
                continue
            if not _defines_gateway_bearer(role, variable):
                offenders.append(
                    f"{role.name}: probes with {variable}, which vars/main.yml "
                    f"does not read from {_CREDENTIAL_KEY}"
                )
            if not _starts_sidecar_with(role, variable):
                offenders.append(
                    f"{role.name}: probes with {variable} but starts its sidecar "
                    f"with a different {_ADAPTER_ENV}"
                )
        self.assertEqual(
            [],
            offenders,
            f"MCP adapter provider(s) probing with the wrong credential "
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

"""The digests ``meta/mcp.yml`` pins match the contract files they pin.

Two fields pin the same artefact from different angles. ``tools.schema_sha256``
hashes the parsed tool mapping the role loads into the adapter contract; the
adapter rehashes it at startup and refuses to serve on a mismatch, so a stale
pin becomes a container that never turns healthy, an hour into a deploy,
reported as a failing probe rather than as the metadata edit it is.
``adapter.specification_sha256`` hashes the checked-in specification file
byte-for-byte and is enforced nowhere at runtime, which is precisely why it
needs a check here: a pin nothing recomputes is indistinguishable from a pin
somebody typed.

The tool digest is computed with the adapter's own ``policy.schema_digest``
rather than a reimplementation, so the check cannot drift from the code that
enforces it in production.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-contract-digest`` on, or directly above, the pinning line.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_for_key
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_RULE = "mcp-contract-digest"
_ADAPTER_FILES = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files"
_CONTRACT_RELATIVE = "files/mcp/tools.json"


def _schema_digest(tools: dict) -> str:
    """Return the digest the adapter itself would compute for *tools*."""
    spec = importlib.util.spec_from_file_location(
        "adapter_policy", _ADAPTER_FILES / "policy.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(_ADAPTER_FILES))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(_ADAPTER_FILES))
    return module.schema_digest(tools)


def _file_digest(path: Path) -> str:
    """Return the byte-exact sha256 of *path*, prefixed like the pin."""
    raw = path.read_bytes()  # nocheck: cache-read  no newline translation
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class TestMcpContractDigest(unittest.TestCase):
    def test_every_pinned_digest_matches_its_contract(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        offenders: list[str] = []
        checked = 0
        for mcp_path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_MCP}")):
            mcp = load_yaml_any(str(mcp_path), default_if_missing={}) or {}
            role_dir = mcp_path.parent.parent
            lines = read_text(str(mcp_path)).splitlines()

            pinned = str((mcp.get("tools") or {}).get("schema_sha256") or "")
            if pinned and not is_suppressed_for_key(lines, "schema_sha256", _RULE):
                contract_path = role_dir / _CONTRACT_RELATIVE
                if not contract_path.is_file():
                    offenders.append(
                        f"{role_dir.name}: pins tools.schema_sha256 but ships no "
                        f"{_CONTRACT_RELATIVE}"
                    )
                else:
                    found = _schema_digest(json.loads(read_text(str(contract_path))))
                    checked += 1
                    if found != pinned:
                        offenders.append(
                            f"{role_dir.name}: tools.schema_sha256 pins {pinned} "
                            f"but {_CONTRACT_RELATIVE} hashes to {found}; renew "
                            f"the pin"
                        )

            adapter = mcp.get("adapter") or {}
            spec_pin = str(adapter.get("specification_sha256") or "")
            spec_path = str(adapter.get("specification_path") or "")
            if (
                spec_pin
                and spec_path
                and not is_suppressed_for_key(lines, "specification_sha256", _RULE)
            ):
                specification = PROJECT_ROOT / spec_path
                if not specification.is_file():
                    offenders.append(
                        f"{role_dir.name}: adapter.specification_path {spec_path!r} "
                        f"does not exist"
                    )
                else:
                    found = _file_digest(specification)
                    checked += 1
                    if found != spec_pin:
                        offenders.append(
                            f"{role_dir.name}: adapter.specification_sha256 pins "
                            f"{spec_pin} but {spec_path} hashes to {found}; renew "
                            f"the pin"
                        )

        self.assertEqual(
            [],
            offenders,
            f"contract digest drift ({len(offenders)}):\n"
            + "\n".join(f"  - {o}" for o in offenders),
        )
        self.assertTrue(
            checked,
            "no role pins a contract digest, so the rule would pass vacuously; "
            "check that the scan still reads the right topic",
        )

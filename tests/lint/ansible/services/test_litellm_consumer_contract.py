"""Lint: every LiteLLM consumer role is bound by the gateway's own contract.

``svc-ai-litellm/tasks/utils/consumer_contract.yml`` is the single place that
refuses an empty virtual key and an AI base URL pointing outside the container
network. A role that declares the ``litellm`` service but never includes it
still renders its AI configuration, so a missing key or a public endpoint
reaches a green deploy and every prompt leaves the deployment unauthenticated.

The scan derives the consumer set from the repository rather than from a list:
a ``litellm`` block without ``modes`` is a consumer flag, while the gateway
(``svc-ai-litellm``) and its admin UI (``web-app-litellm``) declare the service
they run and are not bound by the contract they own.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: litellm-consumer-contract`` in the head of the role's
  ``meta/services.yml``.
"""

from __future__ import annotations

import os
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "litellm-consumer-contract"
_SERVICE = "litellm"
_CREDENTIAL = "litellm_api_key"
_CONTRACT = "roles/svc-ai-litellm/tasks/utils/consumer_contract.yml"


def _consumer_roles() -> list[Path]:
    """Return the role directories that consume the shared gateway."""
    roles: list[Path] = []
    for services_path in sorted(
        Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
    ):
        services = load_yaml_any(str(services_path), default_if_missing={})
        if not isinstance(services, Mapping):
            continue
        block = services.get(_SERVICE)
        if not isinstance(block, Mapping) or "modes" in block:
            continue
        if is_suppressed_in_head(read_text(str(services_path)).splitlines(), _RULE):
            continue
        roles.append(services_path.parent.parent)
    return roles


def _declares_credential(role: Path) -> bool:
    secrets = load_yaml_any(str(role / ROLE_FILE_META_SECRETS), default_if_missing={})
    if not isinstance(secrets, Mapping):
        return False
    credentials = secrets.get("credentials")
    return isinstance(credentials, Mapping) and _CREDENTIAL in credentials


def _includes_contract(role: Path) -> bool:
    tasks_dir = str(role / "tasks") + os.sep
    return any(
        path.startswith(tasks_dir) and _CONTRACT in content
        for path, content in iter_project_files_with_content(extensions=(".yml",))
    )


class TestLitellmConsumerContract(unittest.TestCase):
    def test_every_consumer_mints_its_own_virtual_key(self) -> None:
        missing = [
            f"{role.name}: declares services.{_SERVICE} but no "
            f"credentials.{_CREDENTIAL} in {ROLE_FILE_META_SECRETS}, so its AI "
            f"surface would authenticate with a shared or empty key"
            for role in _consumer_roles()
            if not _declares_credential(role)
        ]
        self.assertEqual(
            [],
            missing,
            f"LiteLLM consumer role(s) without their own virtual key "
            f"({len(missing)}):\n" + "\n".join(f"  - {m}" for m in missing),
        )

    def test_every_consumer_includes_the_gateway_contract(self) -> None:
        missing = [
            f"{role.name}: declares services.{_SERVICE} but no task includes "
            f"{_CONTRACT}, so neither the empty-key guard nor the "
            f"stays-in-the-deployment guard runs for this role"
            for role in _consumer_roles()
            if not _includes_contract(role)
        ]
        self.assertEqual(
            [],
            missing,
            f"LiteLLM consumer role(s) without the gateway contract "
            f"({len(missing)}):\n" + "\n".join(f"  - {m}" for m in missing),
        )

    def test_the_scan_finds_consumer_roles(self) -> None:
        self.assertTrue(
            _consumer_roles(),
            "no role consumes services.litellm, so both rules would pass "
            "vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()

"""Warn-only external check: the pinned adapter base digest still is the tag's.

Each MCP adapter builds ``FROM <image>@<digest>``, where the image and tag come
from the role's own sidecar service in ``meta/services.yml`` and the digest from
``mcp.adapter.digest`` in ``meta/mcp.yml``. The mirror, in contrast, copies by
tag: ``skopeo copy`` reproduces whatever the tag points at when the sync runs.
Once upstream moves the tag, the pinned digest is a manifest the mirror was
never asked to copy, so a mirrored build resolves ``FROM`` to nothing while a
direct build keeps working, which is why the drift shows up as a build failure
in exactly one deployment mode.

Warn-only and opt-in like its neighbours in this package: a moved upstream tag
is not a defect in the change under review, and a registry outage must not fail
an unrelated pull request. The pin is renewed deliberately, in its own change.
"""

from __future__ import annotations

import unittest

from utils.annotations.message import warning as gha_warning
from utils.cache.yaml import load_yaml_any
from utils.docker.registry import manifest_digest
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_SIDECAR_SUFFIX = "mcp"


def _sidecar_ref(role_dir) -> tuple[str, str] | None:
    """Return ``(image, version)`` of the role's adapter sidecar service."""
    services = load_yaml_any(
        str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    if not isinstance(services, dict):
        return None
    for name, service in services.items():
        if not isinstance(service, dict) or not str(name).endswith(_SIDECAR_SUFFIX):
            continue
        image = str(service.get("image") or "").strip()
        version = str(service.get("version") or "").strip()
        if image and version:
            return image, version
    return None


class TestMcpAdapterBaseDigest(unittest.TestCase):
    """Warn-only: surface adapter base pins that no longer match their tag."""

    def test_pinned_base_digests_are_current(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        for mcp_path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_MCP}")):
            mcp = load_yaml_any(str(mcp_path), default_if_missing={})
            pinned = str(((mcp or {}).get("adapter") or {}).get("digest") or "")
            if not pinned:
                continue

            role_dir = mcp_path.parent.parent
            reference = _sidecar_ref(role_dir)
            if reference is None:
                gha_warning(
                    f"{role_dir.name} pins mcp.adapter.digest but declares no "
                    f"sidecar service carrying the base image and version",
                    file=str(mcp_path.relative_to(PROJECT_ROOT)),
                )
                continue

            image, version = reference
            current = manifest_digest(image, version)
            if current is None:
                gha_warning(
                    f"{role_dir.name}: could not resolve {image}:{version} "
                    f"upstream; adapter base digest left unchecked",
                    file=str(mcp_path.relative_to(PROJECT_ROOT)),
                )
                continue

            if current != pinned:
                gha_warning(
                    f"{role_dir.name}: mcp.adapter.digest pins {pinned} but "
                    f"{image}:{version} now resolves to {current}; the mirror "
                    f"copies the tag, so a mirrored build cannot pull the old "
                    f"manifest",
                    file=str(mcp_path.relative_to(PROJECT_ROOT)),
                )

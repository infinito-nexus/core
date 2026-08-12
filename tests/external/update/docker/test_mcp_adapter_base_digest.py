"""Warn-only external check: the pinned adapter base digest is one you can pull.

Each MCP adapter builds ``FROM <image>@<digest>``, where image and tag come from
the role's own sidecar service in ``meta/services.yml`` and the digest from
``mcp.adapter.digest`` in ``meta/mcp.yml``. Where a GHCR mirror is configured the
build resolves that reference against the mirror, and the mirror is copied by
tag: it holds whatever the tag pointed at when the sync last ran, which lags
upstream by design. Pinning the newest upstream digest therefore breaks exactly
the mirrored build it was meant to protect - observed as
``mirror/docker.io/python@sha256:...: not found`` in run 31374959721.

So the mirror is the authority when one is configured, and upstream only when
none is. A pin that resolves in neither is reported; a pin that merely differs
from the current upstream tag is not, because the mirror lagging upstream is the
sync's business, not the pin's.

Warn-only and opt-in like its neighbours in this package: a registry outage must
not fail an unrelated pull request, and the pin is renewed deliberately, in its
own change.
"""

from __future__ import annotations

import unittest

from utils.annotations.message import warning as gha_warning
from utils.cache.yaml import load_yaml_any
from utils.docker.mirror import mirror_image
from utils.docker.registry import manifest_digest, manifest_exists
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
            source = mirror_image(image) or image
            if manifest_exists(source, pinned):
                continue

            current = manifest_digest(source, version)
            if current is None:
                gha_warning(
                    f"{role_dir.name}: could not resolve {source}:{version}; "
                    f"adapter base digest left unchecked",
                    file=str(mcp_path.relative_to(PROJECT_ROOT)),
                )
                continue

            if current != pinned:
                gha_warning(
                    f"{role_dir.name}: mcp.adapter.digest pins {pinned}, which "
                    f"{source} does not serve; its {version} tag holds "
                    f"{current}. A build resolves the pin against this registry, "
                    f"so pin what it serves",
                    file=str(mcp_path.relative_to(PROJECT_ROOT)),
                )

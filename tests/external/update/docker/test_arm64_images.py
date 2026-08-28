"""Verify the roles promised on arm64 pin images that publish an arm64 manifest.

Three requirements place roles on Raspberry-Pi-class nodes, and nothing in the
repository holds them to it: ``platform_arch`` exists only to pin a role to a
single architecture, so a role that must run *everywhere* declares nothing, and
an image bump to an amd64-only tag turns the promise into a scheduling failure
on the Pi rather than a red test here.

The scope is deliberately narrow, and every entry names the requirement that
demands it, so the list stays auditable rather than arbitrary:

* ``web-app-homeassistant`` — 033, "The role runs on arm64"
* ``web-app-hermes``, ``web-app-openclaw`` — 032, "Agents run on arm64 and are
  scheduled across at least two kata-capable nodes"
* ``svc-ai-robot`` — 034, "The role runs on arm64"

``svc-ai-robot`` pins no image of its own: it admits an agent role onto a
dedicated device rather than running a container, so the agent images above
carry its promise and only the placement check applies to it.

Two checks, one offline and one live:

* no role in the set pins ``platform_arch`` to an architecture that excludes
  arm64, because that renders a placement constraint keeping it off the Pi;
* every image the set pins publishes a ``linux/arm64`` manifest.

Indeterminate registry answers only warn, matching ``test_image_reachable.py``:
a rate limit must never read as a missing architecture.

Opt-in external test: it hits live third-party registries and is only run under
the external suite.
"""

from __future__ import annotations

import concurrent.futures
import unittest

from utils.annotations.message import warning
from utils.docker.image.discovery import iter_role_images
from utils.docker.registry import fetch_manifest
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import resolve_max_fetch_workers

from . import PROJECT_ROOT

ARM64 = "arm64"
LINUX = "linux"

ARM64_ROLES = {
    "web-app-homeassistant": "033",
    "web-app-hermes": "032",
    "web-app-openclaw": "032",
    "svc-ai-robot": "034",
}

ARM64_ROLES_WITHOUT_IMAGE = {"svc-ai-robot"}

ARM64_COMPATIBLE_ARCHES = {"aarch64", "armv7l"}


def _pull_image(ref) -> str:
    return ref.name if ref.registry == "docker.io" else f"{ref.registry}/{ref.name}"


def _publishes_arm64(image: str, version: str) -> bool | None:
    """Return whether ``image:version`` offers a linux/arm64 manifest.

    ``None`` when the registry answer does not settle it: an unreachable
    registry, or a single-platform manifest whose architecture lives in a
    config blob this check does not fetch.
    """
    manifest = fetch_manifest(image, version)
    if manifest is None:
        return None
    entries = manifest.get("manifests")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        platform = (entry or {}).get("platform") or {}
        if platform.get("os") == LINUX and platform.get("architecture") == ARM64:
            return True
    return False


class TestArm64Images(unittest.TestCase):
    def setUp(self) -> None:
        self.refs = [
            ref for ref in iter_role_images(PROJECT_ROOT) if ref.role in ARM64_ROLES
        ]

    def test_the_scan_finds_every_promised_role(self) -> None:
        found = {ref.role for ref in self.refs}
        missing = sorted(ARM64_ROLES.keys() - ARM64_ROLES_WITHOUT_IMAGE - found)
        self.assertEqual(
            [],
            missing,
            "role(s) promised on arm64 whose pinned image the scan did not "
            f"find, so the rule would pass vacuously for them: {missing}",
        )

    def test_no_promised_role_is_pinned_off_arm64(self) -> None:
        from utils.cache.yaml import load_yaml_any

        offenders = []
        for role, requirement in sorted(ARM64_ROLES.items()):
            services = load_yaml_any(
                str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES),
                default_if_missing={},
            )
            if not isinstance(services, dict):
                continue
            for service_name, service in services.items():
                if not isinstance(service, dict):
                    continue
                arch = service.get("platform_arch")
                if arch is None or str(arch) in ARM64_COMPATIBLE_ARCHES:
                    continue
                offenders.append(
                    f"{role}/{service_name}: platform_arch '{arch}' renders a "
                    f"placement constraint that keeps requirement {requirement}'s "
                    f"role off every arm64 node"
                )
        self.assertEqual(
            [],
            offenders,
            "role(s) pinned away from arm64:\n"
            + "\n".join(f"  - {o}" for o in offenders),
        )

    def test_every_promised_image_publishes_arm64(self) -> None:
        pairs = {(_pull_image(ref), ref.version) for ref in self.refs}

        def _check(pair: tuple[str, str]) -> tuple[tuple[str, str], bool | None]:
            return pair, _publishes_arm64(*pair)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=resolve_max_fetch_workers()
        ) as pool:
            results = dict(pool.map(_check, pairs))

        missing = []
        for ref in self.refs:
            status = results.get((_pull_image(ref), ref.version))
            image = f"{_pull_image(ref)}:{ref.version}"
            if status is False:
                missing.append(
                    f"{ref.role}/{ref.service}: {image} publishes no linux/arm64 "
                    f"manifest, so requirement {ARM64_ROLES[ref.role]}'s arm64 "
                    f"promise cannot hold"
                )
            elif status is None:
                warning(
                    f"{ref.role}/{ref.service}: {image} arm64 availability could "
                    f"not be verified (network / auth / rate-limit / "
                    f"single-platform manifest)",
                    title="🔍 Unverified arm64 image",
                    file=f"roles/{ref.role}/{ROLE_FILE_META_SERVICES}",
                )

        self.assertEqual(
            [],
            missing,
            "image(s) without an arm64 manifest:\n"
            + "\n".join(f"  - {m}" for m in missing),
        )


if __name__ == "__main__":
    unittest.main()

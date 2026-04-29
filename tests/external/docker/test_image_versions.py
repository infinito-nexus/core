"""Check Docker image versions in roles/web-*/meta/services.yml.

For each service with a semver-compatible version tag the latest available
tag on Docker Hub is fetched and compared. Outdated versions are reported as
GitHub Actions ``::warning::`` annotations or plain stdout warnings.

This is an opt-in external test because it depends on live third-party
registries. The test always passes so normal validation stays stable even when
registries are slow or temporarily unavailable. Developers are notified of
available updates via the warning output.

Semver-compatible version formats checked:
  x  /  x.x  /  x.x.x  /  x.x.x.x  (with optional leading ``v``)

Flavored Docker Official Image tags of the form
``<semver>-<flavor>`` (e.g. ``5.4.5-php8.3-apache``) are also recognised;
upgrade candidates must share the same ``-<flavor>`` suffix so the check
never silently proposes a different runtime/webserver variant.

Suppress a check by placing ``# nocheck: docker-version`` on the line
directly above the ``version:`` key (blank lines between are ignored,
but any non-comment line resets the search):

    # nocheck: docker-version
    version: "4.5"
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.annotations.message import warning
from utils.docker.version_updater import (
    fetch_dockerhub_tags,
    fetch_ghcr_tags,
    is_dockerhub,
    is_ghcr,
    is_semver,
    latest_semver,
    suppressed_services,
    version_depth,
    version_flavor,
    version_key,
)

from utils.docker.image.discovery import iter_role_images

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ROLES_ROOT = _REPO_ROOT / "roles"


def _collect_entries() -> list[dict]:
    """Collect (role, service, image, version, config_path) for semver versions in web-* roles."""
    entries: list[dict] = []
    for ref in iter_role_images(_REPO_ROOT):
        # Only web-* roles
        if not ref.role.startswith("web-"):
            continue
        # Only services from meta/services.yml, not defaults/main.yml.
        if ref.source_file != "meta/services.yml":
            continue
        # Only semver versions (pure or `<semver>-<flavor>`)
        if not is_semver(ref.version):
            continue
        cfg_path = _ROLES_ROOT / ref.role / "meta" / "services.yml"
        # Check nocheck suppression
        if ref.service in suppressed_services(cfg_path):
            continue
        # Reconstruct full image reference for registry API calls
        if ref.registry == "docker.io":
            image = ref.name
        else:
            image = f"{ref.registry}/{ref.name}"
        entries.append(
            {
                "role": ref.role,
                "service": ref.service,
                "image": image,
                "version": ref.version,
                "config_path": str(cfg_path.relative_to(_REPO_ROOT)),
            }
        )
    return entries


def _emit_annotation(
    config_path: str,
    role: str,
    service: str,
    image: str,
    current: str,
    latest: str,
) -> None:
    msg = f"{role}/{service}: {image} is at {current}, latest semver tag is {latest}"
    warning(msg, title="Outdated Docker image", file=config_path)


def _emit_unchecked_annotation(
    config_path: str,
    role: str,
    service: str,
    image: str,
) -> None:
    msg = (
        f"{role}/{service}: {image} version could not be checked "
        f"(registry not supported)"
    )
    warning(msg, title="🔍 Unchecked Docker image", file=config_path)


class TestDockerImageVersions(unittest.TestCase):
    """Warn about outdated live Docker image versions in roles/web-*/meta/services.yml."""

    def test_image_versions_are_current(self) -> None:
        entries = _collect_entries()
        self.assertTrue(entries, "No semver-versioned config entries found")

        # Deduplicate registry queries per image
        image_tags: dict[str, list[str]] = {}
        for e in entries:
            img = e["image"]
            if img in image_tags:
                continue
            if is_dockerhub(img):
                image_tags[img] = fetch_dockerhub_tags(img)
            elif is_ghcr(img):
                image_tags[img] = fetch_ghcr_tags(img)

        outdated: list[dict] = []
        unchecked: list[dict] = []
        for e in entries:
            img = e["image"]
            if not is_dockerhub(img) and not is_ghcr(img):
                unchecked.append(e)
                continue
            tags = image_tags.get(img, [])
            if not tags:
                unchecked.append(e)
                continue
            latest = latest_semver(
                tags,
                version_depth(e["version"]),
                version_flavor(e["version"]),
            )
            if latest and version_key(e["version"]) < version_key(latest):
                outdated.append({**e, "latest": latest})

        if outdated:
            col_w = (35, 20, 40, 15)
            header = (
                f"{'Role':<{col_w[0]}} {'Service':<{col_w[1]}} "
                f"{'Image':<{col_w[2]}} {'Current':<{col_w[3]}} Latest"
            )
            rows = "\n".join(
                f"{o['role']:<{col_w[0]}} {o['service']:<{col_w[1]}} "
                f"{o['image']:<{col_w[2]}} {o['version']:<{col_w[3]}} {o['latest']}"
                for o in outdated
            )
            print(
                f"\n⚠️  Outdated Docker image versions:\n{header}\n{'-' * 120}\n{rows}\n\n💡 To suppress a warning add above the version: key:\n  # nocheck: docker-version"
            )
            for o in outdated:
                _emit_annotation(
                    o["config_path"],
                    o["role"],
                    o["service"],
                    o["image"],
                    o["version"],
                    o["latest"],
                )

        if unchecked:
            col_w = (35, 20, 40, 15)
            header = (
                f"{'Role':<{col_w[0]}} {'Service':<{col_w[1]}} "
                f"{'Image':<{col_w[2]}} Current"
            )
            rows = "\n".join(
                f"{o['role']:<{col_w[0]}} {o['service']:<{col_w[1]}} "
                f"{o['image']:<{col_w[2]}} {o['version']}"
                for o in unchecked
            )
            print(
                f"\n🔍 Unchecked Docker image versions (registry not supported):\n"
                f"{header}\n{'-' * 100}\n{rows}"
            )
            for o in unchecked:
                _emit_unchecked_annotation(
                    o["config_path"],
                    o["role"],
                    o["service"],
                    o["image"],
                )

        # Always pass - outdated images are warnings, not hard failures
        self.assertIsNotNone(entries)


if __name__ == "__main__":
    unittest.main()

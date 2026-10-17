"""Every path an image declares as a VOLUME must be mounted by its role.

An unmounted ``VOLUME`` does not fail: docker silently creates an anonymous
volume for it. The container then works, and the gap only shows up later, as a
volume nobody can attribute. ``sys-ctl-hlth-volumes`` reports exactly that and
fails the deploy over it, and its whitelist keys on volume ids, which are new
on every deploy, so the gap cannot be suppressed there either.

A child does not cover its parent. ``web-svc-xmpp`` mounted the four paths
below ``/opt/ejabberd`` while the image declares the directory itself, and the
anonymous volume appeared for the parent all the same.

The image side is read from the registry the way the healthcheck sweep reads
it: the manifest names the config blob, the blob carries ``Volumes``. Without
a configured mirror the sweep refuses to run rather than spend the upstream's
anonymous rate limit.

The mount side is attributed, not searched. ``meta/services.yml`` declares the
image under a key that is not always the compose service running it: an entry
with a ``proxy.service_key`` renders under that key as well, and an entry
naming an RDBMS engine renders the provider's partial, whose mounts the
``svc-db-*`` role declares. Both sides are read, because a role may carry
mounts on either.
"""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from utils.annotations.message import in_github_actions
from utils.annotations.suppress import is_suppressed_at
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.docker.image.config import image_volumes
from utils.docker.image.discovery import iter_role_images, load_yaml
from utils.docker.mirror import mirror_image
from utils.roles.applications.services.database import RDBMS_SERVICE_KEYS
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VOLUMES

WORKERS = 16
MIRROR_PROBE = "redis"
RULE = "image-volumes"
RDBMS_PROVIDERS = {key: f"svc-db-{key}" for key in RDBMS_SERVICE_KEYS}


def is_suppressed(role: str, service: str) -> bool:
    """Whether the service entry carries ``# nocheck: image-volumes``."""
    path = PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return False
    lines = read_text(path).splitlines()
    for number, line in enumerate(lines, start=1):
        if line.startswith(f"{service}:"):
            return is_suppressed_at(lines, number, RULE)
    return False


def is_deployed(role: str, service: str) -> bool:
    """Whether the entry is a service at all, rather than a mirror-only image."""
    services = load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES)
    entry = services.get(service) if isinstance(services, dict) else None
    return not (isinstance(entry, dict) and entry.get("enabled") is False)


def service_keys(role: str, service: str) -> set[str]:
    """Return the compose service keys the ``meta/services.yml`` entry renders as.

    Args:
        role: the role directory name.
        service: the ``meta/services.yml`` key the image is declared under.

    Returns:
        The declaring key, plus the entry's ``proxy.service_key`` where it
        names a different one. A templated ``service_key`` resolves per flavor,
        so it contributes nothing and only the declaring key is returned.
    """
    services = load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES)
    entry = services.get(service) if isinstance(services, dict) else None
    proxy = entry.get("proxy") if isinstance(entry, dict) else None
    key = proxy.get("service_key") if isinstance(proxy, dict) else None
    if isinstance(key, str) and "{{" not in key and "{%" not in key:
        return {service, key}
    return {service}


def mount_targets(role: str, services: set[str]) -> set[str]:
    """Return the container paths ``roles/<role>/meta/volumes.yml`` mounts.

    Args:
        role: the role whose ``meta/volumes.yml`` is read.
        services: the compose service keys a mount may name.
    """
    document = load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_VOLUMES)
    targets: set[str] = set()
    if not isinstance(document, dict):
        return targets
    for entry in document.values():
        if not isinstance(entry, dict):
            continue
        for mount in entry.get("mounts") or []:
            if not isinstance(mount, dict):
                continue
            if mount.get("service") in services and isinstance(
                mount.get("target"), str
            ):
                targets.add(mount["target"].rstrip("/") or "/")
    return targets


def declared_targets(role: str, service: str) -> set[str]:
    """Return every container path the deploy mounts into ``service``.

    Args:
        role: the role declaring the image.
        service: the ``meta/services.yml`` key the image is declared under.

    Returns:
        The role's own mounts for every key the entry renders as, widened by
        the ``svc-db-*`` provider's for an RDBMS engine, whose sidecar the
        consumer renders from the provider's partial instead of declaring it.
    """
    targets = mount_targets(role, service_keys(role, service))
    provider = RDBMS_PROVIDERS.get(service)
    if provider is not None:
        targets |= mount_targets(provider, {service})
    return targets


class TestImageVolumesMounted(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if mirror_image(MIRROR_PROBE) is None:
            message = (
                f"no GHCR mirror resolves for '{MIRROR_PROBE}'. The mirror is "
                "what keeps a sweep of every declared image inside the "
                "anonymous rate limit this address shares with every other "
                "pull, so this test does not fall back to the upstream "
                "registries"
            )
            if in_github_actions():
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        cls.refs = sorted(
            iter_role_images(PROJECT_ROOT), key=lambda ref: (ref.role, ref.service)
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            cls.volumes = list(
                pool.map(
                    lambda ref: image_volumes(ref.addressable, ref.version), cls.refs
                )
            )

    def test_every_declared_volume_has_a_mount(self) -> None:
        unmounted: list[str] = []
        indeterminate = 0
        declaring = 0

        for ref, found in zip(self.refs, self.volumes, strict=True):
            if found is None:
                indeterminate += 1
                continue
            if not found:
                continue
            declaring += 1
            if not is_deployed(ref.role, ref.service) or is_suppressed(
                ref.role, ref.service
            ):
                continue
            targets = declared_targets(ref.role, ref.service)
            for declared in sorted(found):
                path = declared.rstrip("/") or "/"
                if path in targets:
                    continue
                unmounted.append(f"{ref.role}:{ref.service} declares {declared}")

        print(
            f"\n{len(self.refs)} image(s): {declaring} declare a VOLUME, "
            f"{indeterminate} unreachable, {len(unmounted)} path(s) unmounted"
        )
        self.assertEqual(
            unmounted,
            [],
            "these images declare a VOLUME their role mounts nothing at, so "
            "docker creates an anonymous volume there and "
            "sys-ctl-hlth-volumes fails the deploy over it. Declare the path "
            f"in meta/volumes.yml, or mark the entry '# nocheck: {RULE}' where "
            "the anonymous volume is intended:\n  " + "\n  ".join(unmounted),
        )

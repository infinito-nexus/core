from __future__ import annotations

import unittest

from plugins.lookup.container_volumes import container_volumes
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

APPLICATION_ID = "web-app-weblate"
VOLUMES = PROJECT_ROOT / "roles" / APPLICATION_ID / ROLE_FILE_META_VOLUMES
CACHE_DIR = "/app/cache"
STATIC_ROOT = f"{CACHE_DIR}/static"
STATIC_MODE = 0o1777


def cache_sharers() -> list[str]:
    """Return every service ``meta/volumes.yml`` mounts the shared cache into.

    Returns:
        The service keys of the mounts whose target is ``CACHE_DIR``, sorted.
    """
    volumes = load_yaml_str(read_text(str(VOLUMES)))
    return sorted(
        {
            mount["service"]
            for entry in volumes.values()
            if entry.get("type", "volume") == "volume"
            for mount in entry.get("mounts") or []
            if mount.get("target") == CACHE_DIR
        }
    )


def rendered_mounts(service: str) -> list[object]:
    """Render the ``volumes:`` list ``compose.yml.j2`` receives for a service.

    Args:
        service: the compose service key.

    Returns:
        The mount entries ``container_volumes`` emits for it.
    """
    rendered = container_volumes({APPLICATION_ID: {}}, APPLICATION_ID, service)
    return load_yaml_str(rendered)["volumes"]


class TestStaticRootPerContainer(unittest.TestCase):
    def test_every_cache_sharer_collects_static_into_its_own_tmpfs(self) -> None:
        sharers = cache_sharers()
        self.assertEqual(sharers, ["beat", "weblate", "worker"])
        for service in sharers:
            with self.subTest(service=service):
                static = [
                    mount
                    for mount in rendered_mounts(service)
                    if isinstance(mount, dict) and mount.get("target") == STATIC_ROOT
                ]
                self.assertEqual(
                    [mount.get("type") for mount in static],
                    ["tmpfs"],
                    f"every Weblate task runs collectstatic into {STATIC_ROOT} on "
                    f"start; on the {CACHE_DIR} volume the tasks share, concurrent "
                    f"runs delete each other's hashed files and the swarm tasks "
                    f"crash-loop with FileNotFoundError, so '{service}' needs a "
                    f"tmpfs of its own there",
                )
                self.assertEqual(
                    (static[0].get("tmpfs") or {}).get("mode"),
                    STATIC_MODE,
                    f"runc mounts a tmpfs with the mode of the directory beneath "
                    f"it once that exists, and on the {CACHE_DIR} volume that is "
                    f"the root-owned 0755 mountpoint the first task left behind; "
                    f"Weblate runs as uid 1000, so collectstatic dies with "
                    f"'PermissionError: ... {STATIC_ROOT}/weblate_fonts' unless "
                    f"the tmpfs of '{service}' declares mode {STATIC_MODE:o}",
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_TEMPL_COMPOSE

ROLE = PROJECT_ROOT / "roles" / "web-app-weblate"
COMPOSE = ROLE / ROLE_FILE_TEMPL_COMPOSE
VOLUMES = ROLE / ROLE_FILE_META_VOLUMES
POPULATING_SERVICE = "beat"


def service_blocks(template: str) -> dict[str, str]:
    """Split a compose template into one text block per ``service_name``.

    Args:
        template: the raw ``compose.yml.j2`` source.

    Returns:
        Mapping of service name to the template text that renders it.
    """
    parts = re.split(r"{%\s*set service_name = '([^']+)'\s*%}", template)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


class TestSharedVolumePopulationOrder(unittest.TestCase):
    def test_every_other_sharer_waits_for_the_service_that_fills_the_volume(
        self,
    ) -> None:
        volumes = load_yaml_str(read_text(str(VOLUMES)))
        sharers = {
            mount["service"]
            for entry in volumes.values()
            for mount in entry.get("mounts") or []
        }
        blocks = service_blocks(read_text(str(COMPOSE)))
        for service in sorted(sharers - {POPULATING_SERVICE}):
            self.assertIn(
                POPULATING_SERVICE,
                blocks[service],
                f"docker fills a fresh named volume from the image once per container "
                f"create and the copy's mkdir is not EEXIST-safe, so '{service}' must "
                f"depend on '{POPULATING_SERVICE}' instead of being created beside it, "
                f"or the deploy dies on 'mkdir /var/lib/docker/volumes/weblate_data/"
                f"_data/python: file exists'",
            )


if __name__ == "__main__":
    unittest.main()

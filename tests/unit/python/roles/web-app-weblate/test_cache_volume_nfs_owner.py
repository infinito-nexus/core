from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

VOLUMES = PROJECT_ROOT / "roles" / "web-app-weblate" / ROLE_FILE_META_VOLUMES


class TestCacheVolumeNfsOwner(unittest.TestCase):
    def test_cache_volume_root_belongs_to_the_weblate_user(self) -> None:
        volumes = load_yaml_str(read_text(str(VOLUMES)))
        self.assertEqual(
            volumes["cache"].get("nfs"),
            {"uid": "1000", "gid": "0", "mode": "0770"},
            "the swarm NFS prep pre-creates the static tmpfs mountpoint inside "
            "weblate_cache, so docker no longer copies the image's 1000:0 0770 "
            "/app/cache onto the volume; the NFS prep has to set that owner and "
            "mode itself, or uid 1000 cannot create /app/cache/avatar, ssh and "
            "matplotlib",
        )


if __name__ == "__main__":
    unittest.main()

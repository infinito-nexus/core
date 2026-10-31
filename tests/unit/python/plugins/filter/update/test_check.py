import unittest

from plugins.filter.update.check import FilterModule, update_check
from utils.update_check.common import FAIL, OK, WARN

NOW = 1_800_000_000
DAY = 86400


def _state(*records):
    return "\n".join(["now\t" + str(NOW), *("\t".join(map(str, r)) for r in records)])


def _applications():
    return {
        "svc-db-postgres": {
            "services": {
                "postgres": {"image": "postgres", "version": "18", "shared": True}
            },
            "volumes": {"data": {"name": "postgres_data"}},
            "networks": {"local": {"subnet": "192.168.10.0/24"}},
        },
        "svc-db-mariadb": {
            "services": {"mariadb": {"image": "mariadb", "version": "11.4"}},
            "volumes": {"data": {"name": "mariadb_data"}},
        },
        "web-app-nextcloud": {
            "services": {
                "nextcloud": {
                    "image": "nextcloud",
                    "version": "34-fpm-alpine",
                    "name": "nextcloud",
                    "ports": {"local": {"http": 8001}, "public": {"smtp": 25}},
                },
                "proxy": {
                    "image": "nginx",
                    "version": "1.31.8",
                    "name": "nextcloud-proxy",
                },
                "redis": {
                    "enabled": True,
                    "shared": True,
                    "image": "redis",
                    "version": "8",
                },
                "talk": {"enabled": "False", "ports": {"public": {"turn": 3478}}},
            },
            "volumes": {
                "data": {
                    "name": "nextcloud_data",
                    "mounts": [{"service": "nextcloud"}],
                },
                "www": {"type": "volume", "path": "/var/www/"},
            },
            "networks": {"local": {"subnet": "192.168.41.0/24"}},
            "domains": {"canonical": ["next.cloud.example.org"], "aliases": []},
            "secrets": {"credentials": {"administrator_password": "set"}},
        },
        "web-app-wordpress": {
            "services": {
                "wordpress": {
                    "image": "wordpress",
                    "version": "6",
                    "name": "wordpress",
                    "lifecycle": "eol",
                    "ports": {
                        "local": {"http": 8001},
                        "public": {"ssh": 22, "smtp": 25},
                    },
                }
            },
            "volumes": {"data": {"name": "wordpress_data"}},
            "networks": {"local": {"subnet": "192.168.41.128/25"}},
            "domains": {"canonical": {"blog": "blog.example.org"}},
        },
        "svc-opt-ssd-hdd": {"volumes": {"mass_storage": {"path": "/mnt/hdd/"}}},
        "web-app-broken": {},
    }


COMPOSE_VOLUMES = {
    "svc-db-postgres": "volumes:\n  data:\n    name: postgres_data\n",
    "svc-db-mariadb": "volumes:\n  data:\n    name: mariadb_data\n",
    "web-app-nextcloud": (
        "volumes:\n  data:\n    name: nextcloud_data\n"
        "  redis:\n    name: nextcloud_redis\n  www: {}\n"
    ),
    "web-app-wordpress": "volumes:\n  data:\n    name: wordpress_data\n  cache: {}\n",
    "web-app-broken": None,
}


def _check(state, rc=0):
    deployed = [
        "svc-db-postgres",
        "svc-db-mariadb",
        "web-app-nextcloud",
        "web-app-wordpress",
        "web-app-broken",
        "sys-ctl-x",
    ]
    return update_check(
        state,
        _applications(),
        ["web-app-nextcloud", "web-app-wordpress", "svc-opt-ssd-hdd", "web-app-gone"],
        deployed,
        COMPOSE_VOLUMES,
        ["alias.example.org"],
        ["/etc/nginx/conf.d/servers/http/", "/etc/nginx/conf.d/servers/https/"],
        {
            "web-app-nextcloud": {
                "credentials": {
                    "administrator_password": {"algorithm": "sha256"},
                    "talk": {"secret": {"description": "s"}},
                }
            }
        },
        rc,
        ["Error: unknown key foo"],
    )


def _rows(result, level):
    return [line for line in result["detail"] if line.startswith(level)]


def _has(result, level, *fragments):
    return any(all(f in line for f in fragments) for line in _rows(result, level))


class TestUpdateCheck(unittest.TestCase):
    def setUp(self):
        self.result = _check(
            _state(
                (
                    "volume",
                    "postgres_data",
                    "/mnt/hdd/data/docker/volumes/postgres_data",
                ),
                ("volume", "mariadb_data", "/data/docker/volumes/mariadb_data/_data"),
                (
                    "volume",
                    "nextcloud_data",
                    "/mnt/hdd/data/docker/volumes/nextcloud_data",
                ),
                (
                    "volume",
                    "wordpress-data",
                    "/data/docker/volumes/wordpress-data/_data",
                ),
                (
                    "volume",
                    "wordpress_cache",
                    "/data/docker/volumes/wordpress_cache/_data",
                ),
                ("volume", "a" * 64, "/data/anon"),
                (
                    "dataversion",
                    "/mnt/hdd/data/docker/volumes/postgres_data/PG_VERSION",
                    "17",
                ),
                (
                    "dataversion",
                    "/data/docker/volumes/mariadb_data/_data/mysql_upgrade_info",
                    "12.0.2-MariaDB",
                ),
                (
                    "dataversion",
                    "/mnt/hdd/data/docker/volumes/nextcloud_data/version.php",
                    "31.0.4",
                ),
                ("container", "/nextcloud", "nextcloud:31-fpm", "running", "nextcloud"),
                ("container", "/redis", "redis:9", "running", "nextcloud"),
                (
                    "container",
                    "/nextcloud-proxy",
                    "nginx:1.31.8",
                    "running",
                    "nextcloud",
                ),
                (
                    "container",
                    "/mailu_front",
                    "ghcr.io/heviat/nginx:2024.06",
                    "running",
                    "mailu",
                ),
                (
                    "container",
                    "/wordpress",
                    "docker.io/library/wordpress:6.8",
                    "exited",
                    "wordpress",
                ),
                ("binding", "/legacy-proxy", "127.0.0.1", "8001", "80/tcp"),
                ("binding", "/other", "127.0.0.1", "8001", "80/tcp"),
                (
                    "listen",
                    'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1,fd=3))',
                    "",
                ),
                (
                    "listen",
                    'tcp LISTEN 0 128 0.0.0.0:25 0.0.0.0:* users:(("nginx",pid=7,fd=3))',
                    "wordpress",
                ),
                ("network", "legacy_default", "192.168.41.0/24"),
                ("network", "nextcloud_default", "192.168.41.0/24"),
                ("webtest", "openresty", "1", "nginx: configuration file test failed"),
                (
                    "servername",
                    "/etc/nginx/conf.d/http/servers/old.conf",
                    "old.example.org _",
                ),
                (
                    "servername",
                    "/etc/nginx/conf.d/http/servers/next.conf",
                    "next.cloud.example.org",
                ),
                (
                    "servername",
                    "/etc/nginx/conf.d/servers/https/stale.conf",
                    "stale.example.org",
                ),
                (
                    "servername",
                    "/etc/nginx/conf.d/servers/https/blog.conf",
                    "blog.example.org",
                ),
                (
                    "cert",
                    "example.org",
                    NOW + 3 * DAY,
                    "example.org,*.cloud.example.org",
                ),
                ("failedunit", "sys-ctl-hlth-msmtp.service"),
                (
                    "backup",
                    "/Backups/abc/backup-docker-to-local",
                    NOW - 10 * DAY,
                    "20260101",
                ),
                ("backup", "/Backups/abc/empty"),
                ("disk", "/", "96%"),
                ("disk", "/mnt/hdd", "40%"),
            ),
            rc=1,
        )

    def test_filter_is_registered(self):
        self.assertIs(FilterModule().filters()["update_check"], update_check)

    def test_inventory(self):
        self.assertTrue(_has(self.result, FAIL, "schema", "unknown key foo"))
        self.assertTrue(_has(self.result, WARN, "web-app-gone", "no application role"))
        self.assertTrue(_has(self.result, FAIL, "web-app-wordpress", "end of life"))
        self.assertTrue(_has(self.result, WARN, "web-app-nextcloud", "talk.secret"))
        self.assertFalse(_has(self.result, WARN, "administrator_password"))

    def test_volumes(self):
        self.assertTrue(
            _has(self.result, FAIL, "wordpress_data", "wordpress-data exists")
        )
        self.assertFalse(_has(self.result, FAIL, "wordpress_cache"))
        self.assertTrue(_has(self.result, WARN, "postgres_data", "mass storage"))
        self.assertTrue(_has(self.result, OK, "nextcloud_data"))
        self.assertTrue(_has(self.result, WARN, "wordpress-data", "no deployed role"))
        self.assertFalse(any("a" * 64 in line for line in self.result["detail"]))
        self.assertTrue(_has(self.result, WARN, "nextcloud_redis", "creates it empty"))
        self.assertFalse(any("nextcloud_www" in line for line in self.result["detail"]))
        self.assertTrue(_has(self.result, OK, "wordpress_cache", "web-app-wordpress"))
        self.assertTrue(_has(self.result, WARN, "web-app-broken", "did not resolve"))

    def test_data_versions(self):
        self.assertTrue(_has(self.result, WARN, "PG_VERSION", "pg_upgrade"))
        self.assertTrue(_has(self.result, FAIL, "mysql_upgrade_info", "downgrade"))
        self.assertTrue(_has(self.result, WARN, "version.php", "3 major step"))

    def test_images(self):
        self.assertTrue(
            _has(self.result, WARN, "nextcloud", "31-fpm -> 34", "skips 2 major")
        )
        self.assertTrue(_has(self.result, OK, "wordpress", "code pins 6"))
        self.assertTrue(_has(self.result, OK, "nextcloud-proxy: nginx:1.31.8"))
        self.assertFalse(any("mailu_front" in line for line in self.result["detail"]))
        self.assertFalse(
            any(line.startswith(f"{FAIL} redis") for line in self.result["detail"])
        )

    def test_ports(self):
        self.assertTrue(
            _has(
                self.result,
                FAIL,
                "8001",
                "local by web-app-nextcloud, web-app-wordpress",
            )
        )
        self.assertTrue(
            _has(self.result, OK, "25: web-app-nextcloud, web-app-wordpress")
        )
        self.assertTrue(_has(self.result, FAIL, "22", "sshd"))
        self.assertFalse(_has(self.result, FAIL, "25:"))
        self.assertTrue(_has(self.result, WARN, "8001/tcp", "legacy-proxy, other"))
        self.assertFalse(any("3478" in line for line in self.result["detail"]))

    def test_networks(self):
        self.assertTrue(
            _has(self.result, FAIL, "192.168.41.0/24", "overlaps web-app-wordpress")
        )
        self.assertTrue(_has(self.result, WARN, "192.168.41.0/24", "legacy_default"))
        self.assertFalse(
            _has(self.result, WARN, "web-app-nextcloud needs it", "nextcloud_default")
        )
        self.assertTrue(_has(self.result, OK, "192.168.10.0/24", "svc-db-postgres"))

    def test_webserver_and_certificates(self):
        self.assertTrue(_has(self.result, FAIL, "openresty", "test failed"))
        self.assertTrue(
            _has(self.result, WARN, "alias.example.org", "redirect has no server block")
        )
        self.assertTrue(
            _has(self.result, WARN, "old.example.org", "current code drops it")
        )
        self.assertTrue(
            _has(self.result, WARN, "stale.example.org", "is loaded", "delete it")
        )
        self.assertTrue(
            _has(self.result, OK, "blog.example.org", "servers/https/blog.conf")
        )
        self.assertTrue(
            _has(self.result, WARN, "next.cloud.example.org", "no server block yet")
        )
        self.assertTrue(_has(self.result, WARN, "old layout", "2 server block files"))
        self.assertTrue(_has(self.result, FAIL, "example.org: expires in 3 days"))
        self.assertTrue(_has(self.result, WARN, "blog.example.org", "no certificate"))
        self.assertFalse(
            _has(self.result, WARN, "next.cloud.example.org", "no certificate")
        )

    def test_operations(self):
        self.assertTrue(_has(self.result, WARN, "sys-ctl-hlth-msmtp.service"))
        self.assertTrue(_has(self.result, FAIL, "backup-docker-to-local", "240 hours"))
        self.assertTrue(_has(self.result, WARN, "empty", "empty"))
        self.assertTrue(_has(self.result, FAIL, "/: 96% used"))
        self.assertTrue(_has(self.result, OK, "/mnt/hdd: 40% used"))

    def test_summary_lists_failures_first_and_counts_them(self):
        summary = self.result["summary"]
        self.assertTrue(summary[0].startswith(f"{FAIL} {self.result['failures']} "))
        levels = [line.split(" ", 1)[0] for line in summary[1:]]
        self.assertEqual(levels, sorted(levels, key=lambda level: level != FAIL))
        self.assertNotIn(OK, levels)

    def test_green_without_openresty_still_warns(self):
        result = _check(_state(), rc=0)
        self.assertTrue(_has(result, OK, "schema"))
        self.assertTrue(_has(result, WARN, "openresty", "untested"))


if __name__ == "__main__":
    unittest.main()

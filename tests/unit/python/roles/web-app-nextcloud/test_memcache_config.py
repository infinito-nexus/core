from __future__ import annotations

import unittest

from jinja2 import ChainableUndefined, Environment, select_autoescape

from plugins.lookup.container_volumes import container_volumes
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = "roles/web-app-nextcloud"
APPLICATION_ID = "web-app-nextcloud"
SERVICES = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_META_SERVICES))
VARS = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_VARS_MAIN))
MEMCACHE_TEMPLATE = read_text(
    str(PROJECT_ROOT / ROLE / "templates" / "config" / "memcache.config.php.j2")
)
LOADER_TARGET = "/var/www/infinito/"
REDIS = {
    "host": "redis",
    "port": 6379,
    "username": "default",
    "password": "current-secret",
}


def _render_memcache(compose_mode: bool, redis: dict) -> str:
    env = Environment(
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.globals["lookup"] = lambda name, engine, app, key: redis[key]
    return env.from_string(MEMCACHE_TEMPLATE).render(
        IS_COMPOSE_MODE=compose_mode,
        IS_SWARM_MODE=not compose_mode,
        application_id=APPLICATION_ID,
    )


def _render_jinja(expression: str) -> str:
    env = Environment(
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.globals["lookup"] = lambda name, *args, **kwargs: f"<{name} {args!r}>"
    env.filters["path_join"] = lambda parts: "/".join(str(part) for part in parts)
    return env.from_string(expression).render()


def _mounts(service: str) -> str:
    return container_volumes(
        {APPLICATION_ID: {"services": SERVICES}},
        APPLICATION_ID,
        service,
        render_jinja=_render_jinja,
    )


class TestMemcacheConfig(unittest.TestCase):
    def test_compose_mode_renders_the_current_redis_connection(self):
        rendered = _render_memcache(True, REDIS)
        self.assertIn(r"'memcache.distributed' => '\\OC\\Memcache\\Redis'", rendered)
        self.assertIn(r"'memcache.locking' => '\\OC\\Memcache\\Redis'", rendered)
        self.assertIn("'host' => 'redis'", rendered)
        self.assertIn("'user' => 'default'", rendered)
        self.assertIn("'password' => 'current-secret'", rendered)

    def test_both_modes_render_the_same_config(self):
        self.assertEqual(_render_memcache(True, REDIS), _render_memcache(False, REDIS))

    def test_a_redis_without_auth_renders_no_credentials(self):
        rendered = _render_memcache(True, {**REDIS, "username": "", "password": ""})
        self.assertIn("'host' => 'redis'", rendered)
        self.assertNotIn("'user'", rendered)
        self.assertNotIn("'password'", rendered)

    def test_password_quotes_and_backslashes_stay_inside_the_php_string(self):
        rendered = _render_memcache(True, {**REDIS, "password": "a'b\\c"})
        self.assertIn("'password' => 'a\\'b\\\\c'", rendered)

    def test_every_php_service_mounts_the_loader_that_carries_the_connection(self):
        for service in (
            "nextcloud",
            VARS["NEXTCLOUD_CRON_SERVICE"],
            VARS["NEXTCLOUD_TASKPROCESSING_SERVICE"],
        ):
            with self.subTest(service=service):
                self.assertIn(LOADER_TARGET, _mounts(service))


if __name__ == "__main__":
    unittest.main()

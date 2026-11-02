import re
import shlex
import unittest

import jinja2

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_str
from utils.roles.db.instances import build_instances
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

TEMPLATE = f"roles/svc-db-redis/{ROLE_FILE_TEMPL_COMPOSE}"
HOSTS = ["mgr-01", "mgr-02", "mgr-03"]


def _render(hosts):
    instances = build_instances(
        "svc-db-redis", hosts, deployment_mode="swarm", swarm_nodes=hosts
    )

    def lookup(name, *_args, **_kwargs):
        if name == "db_instances":
            return instances
        if name == "container_image":
            return f"image: redis-{_args[1]}"
        return ""

    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False),
        loader=jinja2.ChoiceLoader(
            [
                jinja2.DictLoader(
                    {
                        "roles/sys-svc-compose/templates/base.yml.j2": "services:\n\n",
                        "roles/sys-svc-container/templates/base.yml.j2": "",
                        "roles/sys-svc-compose/templates/db_endpoint.yml.j2": (
                            "  {{ service_name }}:\n    image: haproxy\n"
                        ),
                    }
                ),
                jinja2.FileSystemLoader(str(PROJECT_ROOT)),
            ]
        ),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    env.filters["quote"] = shlex.quote
    env.globals["lookup"] = lookup
    rendered = env.get_template(TEMPLATE).render(
        application_id="svc-db-redis",
        entity_name="redis",
        REDIS_CONTAINER="redis-central",
        REDIS_PASSWORD="pw",
        REDIS_MAXMEMORY_MB=409,
        REDIS_EXPOSE_LOCAL=False,
        REDIS_HA_MASTER_NAME="redis",
        REDIS_HA_PORT=6379,
        REDIS_SENTINEL_PORT=26379,
        REDIS_SENTINEL_USER="sentinel",
        REDIS_SENTINEL_QUORUM=2,
        REDIS_SENTINEL_DOWN_AFTER_MS=5000,
        REDIS_SENTINEL_FAILOVER_TIMEOUT_MS=10000,
        REDIS_SENTINEL_PARALLEL_SYNCS=1,
        REDIS_HA_START="/start",
        REDIS_HA_INCLUDE="/include.conf",
        REDIS_HA_CONF="/data/redis.conf",
        REDIS_SENTINEL_START="/sentinel-start",
        REDIS_SENTINEL_PASSWORD_FILE="/pw",
        REDIS_SENTINEL_CONF="/data/sentinel.conf",
    )
    return load_yaml_str(rendered)["services"]


class TestRedisComposeHa(unittest.TestCase):
    def test_ha_renders_instances_sentinels_and_endpoint(self):
        services = _render(HOSTS)
        self.assertEqual(
            sorted(services),
            [
                "redis",
                "redis-mgr-01",
                "redis-mgr-02",
                "redis-mgr-03",
                "redis-sentinel-mgr-01",
                "redis-sentinel-mgr-02",
                "redis-sentinel-mgr-03",
            ],
        )
        self.assertEqual(services["redis"]["image"], "haproxy")

    def test_instances_start_through_the_wrapper(self):
        env = _render(HOSTS)["redis-mgr-02"]["environment"]
        self.assertEqual(env["REDIS_HA_SELF"], "redis-mgr-02")
        self.assertEqual(env["REDIS_HA_BOOTSTRAP"], "redis-mgr-01")
        self.assertEqual(
            env["REDIS_HA_SENTINELS"].split(),
            [
                "redis-sentinel-mgr-01",
                "redis-sentinel-mgr-02",
                "redis-sentinel-mgr-03",
            ],
        )

    def test_sentinels_announce_themselves_and_know_their_peers(self):
        services = _render(HOSTS)
        sentinel = services["redis-sentinel-mgr-03"]
        self.assertEqual(sentinel["image"], services["redis-mgr-03"]["image"])
        self.assertTrue(sentinel["read_only"])
        env = sentinel["environment"]
        self.assertEqual(env["SENTINEL_SELF"], "redis-sentinel-mgr-03")
        self.assertEqual(
            env["SENTINEL_PEERS"].split(),
            ["redis-sentinel-mgr-01", "redis-sentinel-mgr-02"],
        )
        self.assertEqual(env["SENTINEL_QUORUM"], "2")

    def test_standalone_keeps_the_flag_command_and_no_sentinel(self):
        services = _render(["mgr-01"])
        self.assertEqual(list(services), ["redis"])
        self.assertIn("--requirepass pw", services["redis"]["command"][2])
        self.assertNotIn("environment", services["redis"])


if __name__ == "__main__":
    unittest.main()

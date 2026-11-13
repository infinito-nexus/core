from __future__ import annotations

import hashlib
import re
import unittest

from jinja2 import (
    ChainableUndefined,
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    select_autoescape,
)

from utils.cache.files import PROJECT_ROOT
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

TEMPLATE = f"roles/web-app-erpnext/{ROLE_FILE_TEMPL_COMPOSE}"
REDIS_CONSUMERS = ("backend", "queue-short", "queue-long", "websocket", "scheduler")
REPLACED_URL = "redis://default:replaced-secret@redis:6379"
ROTATED_URL = "redis://default:rotated-secret@redis:6379"
DIGEST_WRITE = re.compile(
    r'bench set-config -g infinito_configurator_digest "([0-9a-f]{64})";'
)


class _Marker(ChainableUndefined):
    def __str__(self):
        return f"<{self._undefined_name}>"

    __repr__ = __str__


def _render(redis_url: str) -> str:
    env = Environment(
        loader=ChoiceLoader(
            [
                DictLoader(
                    {
                        "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
                        "roles/sys-svc-container/templates/base.yml.j2": "    <container-base>\n",
                    }
                ),
                FileSystemLoader(str(PROJECT_ROOT)),
            ]
        ),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=_Marker,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["hash"] = lambda value, algorithm: hashlib.new(
        algorithm, str(value).encode()
    ).hexdigest()
    env.globals["lookup"] = lambda name, *args, **kwargs: f"<lookup {name} {args!r}>"
    return env.get_template(TEMPLATE).render(
        application_id="web-app-erpnext",
        ERPNEXT_REDIS_URL=redis_url,
        ERPNEXT_DB_HOST="mariadb",
        ERPNEXT_DB_PORT=3306,
        ERPNEXT_BACKEND_PORT=8000,
        ERPNEXT_WEBSOCKET_PORT=9000,
        ERPNEXT_SITES_DIR="/home/frappe/frappe-bench/sites",
    )


def _block(rendered: str, service: str) -> str:
    lines = rendered.splitlines()
    start = lines.index(f"  {service}:")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip() and not lines[index].startswith("   ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


class TestConfiguratorGate(unittest.TestCase):
    def test_the_configurator_writes_its_digest_after_every_redis_url(self):
        command = _block(_render(ROTATED_URL), "configurator")
        digest_write = DIGEST_WRITE.search(command)
        self.assertIsNotNone(digest_write, command)
        for key in ("redis_cache", "redis_queue", "redis_socketio"):
            with self.subTest(key=key):
                self.assertLess(
                    command.index(f"set-config -g {key} "), digest_write.start()
                )

    def test_a_failed_step_stops_the_configurator_before_the_digest(self):
        command = _block(_render(ROTATED_URL), "configurator")
        digest_write = DIGEST_WRITE.search(command)
        self.assertIsNotNone(digest_write, command)
        self.assertLess(command.index("set -e;"), command.index("ls -1 apps"))

    def test_every_redis_consumer_waits_for_the_digest_of_the_current_config(self):
        rendered = _render(ROTATED_URL)
        digest_write = DIGEST_WRITE.search(_block(rendered, "configurator"))
        self.assertIsNotNone(digest_write)
        gate = f"until grep -q {digest_write.group(1)} sites/common_site_config.json"
        for service in REDIS_CONSUMERS:
            with self.subTest(service=service):
                self.assertIn(gate, _block(rendered, service))

    def test_a_rotated_redis_password_changes_every_consumer_spec(self):
        replaced = _render(REPLACED_URL)
        rotated = _render(ROTATED_URL)
        for service in REDIS_CONSUMERS:
            with self.subTest(service=service):
                self.assertNotEqual(_block(replaced, service), _block(rotated, service))

    def test_no_redis_consumer_spec_carries_the_password(self):
        rendered = _render(ROTATED_URL)
        for service in REDIS_CONSUMERS:
            with self.subTest(service=service):
                self.assertNotIn("rotated-secret", _block(rendered, service))


if __name__ == "__main__":
    unittest.main()

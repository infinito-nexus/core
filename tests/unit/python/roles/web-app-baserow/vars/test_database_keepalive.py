from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined
from psycopg2.extensions import parse_dsn

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_ROLE_VARS = PROJECT_ROOT / "roles/web-app-baserow" / ROLE_FILE_VARS_MAIN
_SWARM_IPVS_IDLE_TIMEOUT_SECONDS = 900


class TestDatabaseUrlKeepalive(unittest.TestCase):
    def _connection_parameters(self) -> dict[str, str]:
        env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders a connection URI, not markup
        url = env.from_string(
            load_yaml(str(_ROLE_VARS))["BASEROW_DATABASE_URL"]
        ).render(
            BASEROW_DATABASE_USER="baserow",
            BASEROW_DATABASE_PASSWORD="placeholder",
            BASEROW_DATABASE_HOST="postgres",
            BASEROW_DATABASE_PORT="5432",
            BASEROW_DATABASE_NAME="baserow",
        )
        return parse_dsn(url)

    def test_idle_connection_is_probed_before_the_swarm_vip_forgets_it(self) -> None:
        params = self._connection_parameters()
        self.assertEqual(params.get("keepalives"), "1")
        self.assertLess(
            int(params["keepalives_idle"]),
            _SWARM_IPVS_IDLE_TIMEOUT_SECONDS,
            "an idle connection through the swarm service VIP is dropped after "
            f"{_SWARM_IPVS_IDLE_TIMEOUT_SECONDS}s without traffic",
        )


if __name__ == "__main__":
    unittest.main()

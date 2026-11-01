"""The shared proxy's nginx.conf takes its worker limits from the proxy alone.

``nginx.conf`` of ``sys-svc-webserver-core`` renders once, in the scope of
whichever role loads ``svc-prx-openresty`` first. ``WEBSERVER_WORKER_*`` pair the
proxy with that role's ``application_id``, so a 64-pid role capped every vhost at
64 worker_connections.
"""

from __future__ import annotations

import re
import textwrap
import unittest
from pathlib import Path
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache import _reset_cache_for_tests
from utils.cache.carrier import (
    APPLICATIONS_RENDERED_FACT,
    merged_applications_cache_key,
)
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml, load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

_WEBSERVER_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "04_webserver.yml"
_NGINX_CONF = (
    Path(PROJECT_ROOT)
    / "roles"
    / "sys-svc-webserver-core"
    / "templates"
    / "nginx.conf.j2"
)
_OPENRESTY_ROLE = Path(PROJECT_ROOT) / "roles" / "svc-prx-openresty"
_OPENRESTY_SERVICES = _OPENRESTY_ROLE / ROLE_FILE_META_SERVICES
_OPENRESTY_COMPOSE = _OPENRESTY_ROLE / ROLE_FILE_TEMPL_COMPOSE

_FIRST_LOADER = "web-svc-mirror"


def _applications(openresty: dict[str, Any]) -> dict[str, Any]:
    """Return *openresty* as the proxy and a first-loading role with 64 pids, 1 cpu.

    Args:
        openresty: the proxy's ``services.openresty`` entry.
    """
    return {
        "svc-prx-openresty": {"services": {"openresty": openresty}},
        _FIRST_LOADER: {"services": {"mirror": {"cpus": 1, "pids_limit": 64}}},
    }


def _proxy(cpus: float, pids_limit: int, worker_connections: int) -> dict[str, Any]:
    """Return a ``services.openresty`` entry.

    Args:
        cpus: the proxy's ``cpus``.
        pids_limit: the proxy's ``pids_limit``.
        worker_connections: the proxy's ``worker_connections``.
    """
    return {
        "cpus": cpus,
        "pids_limit": pids_limit,
        "worker_connections": worker_connections,
    }


def _shipped() -> dict[str, Any]:
    """Return ``services.openresty`` as ``svc-prx-openresty/meta/services.yml`` ships it."""
    return load_yaml(_OPENRESTY_SERVICES)["openresty"]


class TestWebserverWorkerLimits(unittest.TestCase):
    group_vars: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.group_vars = load_yaml(_WEBSERVER_VARS)

    def setUp(self) -> None:
        self.addCleanup(_reset_cache_for_tests)

    def _render(
        self, expression: str, applications: dict[str, Any], **scope: Any
    ) -> str:
        """Render *expression* through Ansible's Templar over the group_vars.

        Args:
            expression: Jinja source, e.g. ``"{{ WEBSERVER_WORKER_CONNECTIONS }}"``.
            applications: payload ``lookup('applications')`` serves.
            scope: play variables added on top of ``application_id``.

        Returns:
            The rendered text, stripped.
        """
        _reset_cache_for_tests()
        variables: dict[str, Any] = {
            key: trust_as_template(value) if isinstance(value, str) else value
            for key, value in self.group_vars.items()
        }
        variables.update(
            application_id=_FIRST_LOADER,
            RESOURCE_CPUS="0.5",
            RESOURCE_PIDS_LIMIT=512,
            **scope,
        )
        key = merged_applications_cache_key(variables)
        variables[APPLICATIONS_RENDERED_FACT] = {
            "key": [key[0], list(key[1])],
            "applications": applications,
        }
        templar = Templar(loader=DataLoader(), variables=variables)
        return str(templar.template(trust_as_template(expression))).strip()

    def _nginx_worker_lines(self, openresty: dict[str, Any]) -> list[str]:
        """Render the ``worker_*`` directives of the shared ``nginx.conf``.

        Args:
            openresty: the proxy's ``services.openresty`` entry.
        """
        worker_lines = [
            line.strip()
            for line in read_text(str(_NGINX_CONF)).splitlines()
            if line.strip().startswith("worker_")
        ]
        return self._render(
            "\n".join(worker_lines), _applications(openresty)
        ).splitlines()

    def test_proxy_connections_follow_the_proxy_alone(self) -> None:
        for scope in ({}, {"service_name": "mirror"}):
            with self.subTest(**scope):
                self.assertEqual(
                    self._render(
                        "{{ WEBSERVER_PROXY_WORKER_CONNECTIONS }}",
                        _applications(_proxy(4, 256, 4096)),
                        **scope,
                    ),
                    "4096",
                )

    def test_proxy_connections_ignore_pids_limit(self) -> None:
        for pids_limit in (64, 256, 100000):
            with self.subTest(pids_limit=pids_limit):
                self.assertEqual(
                    self._render(
                        "{{ WEBSERVER_PROXY_WORKER_CONNECTIONS }}",
                        _applications(_proxy(0.5, pids_limit, 1234)),
                    ),
                    "1234",
                )

    def test_rlimit_nofile_doubles_the_connections(self) -> None:
        self.assertEqual(
            self._render(
                "{{ WEBSERVER_PROXY_WORKER_RLIMIT_NOFILE }}",
                _applications(_proxy(0.5, 256, 1234)),
            ),
            "2468",
        )

    def test_proxy_processes_follow_the_proxy_alone(self) -> None:
        for scope in ({}, {"service_name": "mirror"}):
            with self.subTest(**scope):
                self.assertEqual(
                    self._render(
                        "{{ WEBSERVER_PROXY_WORKER_PROCESSES }}",
                        _applications(_proxy(4, 256, 4096)),
                        **scope,
                    ),
                    "4",
                )

    def test_a_sub_cpu_proxy_still_runs_one_worker(self) -> None:
        self.assertEqual(
            self._render(
                "{{ WEBSERVER_PROXY_WORKER_PROCESSES }}",
                _applications(_proxy(0.5, 256, 4096)),
            ),
            "1",
        )

    def test_app_internal_limits_still_pair_with_the_play(self) -> None:
        applications = _applications(_proxy(4, 256, 4096))
        self.assertEqual(
            self._render("{{ WEBSERVER_WORKER_CONNECTIONS }}", applications), "64"
        )
        self.assertEqual(
            self._render("{{ WEBSERVER_WORKER_PROCESSES }}", applications), "1"
        )

    def test_shared_proxy_nginx_conf_uses_the_proxy_limits(self) -> None:
        self.assertEqual(
            self._nginx_worker_lines(_proxy(4, 256, 2048)),
            [
                "worker_processes 4;",
                "worker_rlimit_nofile 4096;",
                "worker_connections 2048;",
            ],
        )

    def test_shipped_proxy_limits(self) -> None:
        self.assertEqual(_shipped()["pids_limit"], 256)
        self.assertEqual(
            self._nginx_worker_lines(_shipped()),
            [
                "worker_processes 1;",
                "worker_rlimit_nofile 8192;",
                "worker_connections 4096;",
            ],
        )

    def test_container_nofile_ulimit_allows_the_worker_rlimit(self) -> None:
        match = re.search(
            r"^( *)ulimits:\n(?:\1 .*\n)+",
            read_text(str(_OPENRESTY_COMPOSE)),
            re.MULTILINE,
        )
        self.assertIsNotNone(match, f"{_OPENRESTY_COMPOSE} declares no ulimits")
        applications = _applications(_shipped())
        nofile = load_yaml_str(
            self._render(textwrap.dedent(match.group(0)), applications)
        )["ulimits"]["nofile"]
        rlimit = int(
            self._render("{{ WEBSERVER_PROXY_WORKER_RLIMIT_NOFILE }}", applications)
        )
        self.assertEqual(rlimit, 8192)
        self.assertGreaterEqual(nofile["soft"], rlimit)
        self.assertGreaterEqual(nofile["hard"], rlimit)


if __name__ == "__main__":
    unittest.main()

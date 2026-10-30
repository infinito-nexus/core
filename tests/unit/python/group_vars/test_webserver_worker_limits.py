"""The shared proxy's nginx.conf takes its worker limits from the proxy alone.

``nginx.conf`` of ``sys-svc-webserver-core`` renders once, in the scope of
whichever role loads ``svc-prx-openresty`` first. ``WEBSERVER_WORKER_*`` pair the
proxy with that role's ``application_id``, so a 64-pid role capped every vhost at
64 worker_connections.
"""

from __future__ import annotations

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
from utils.cache.yaml import load_yaml

_WEBSERVER_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "04_webserver.yml"
_NGINX_CONF = (
    Path(PROJECT_ROOT)
    / "roles"
    / "sys-svc-webserver-core"
    / "templates"
    / "nginx.conf.j2"
)

_FIRST_LOADER = "web-svc-mirror"


def _applications(proxy_cpus: float) -> dict[str, Any]:
    """Return a proxy with 256 pids and a first-loading role with 64 pids, 1 cpu.

    Args:
        proxy_cpus: the proxy's ``cpus``.
    """
    return {
        "svc-prx-openresty": {
            "services": {"openresty": {"cpus": proxy_cpus, "pids_limit": 256}}
        },
        _FIRST_LOADER: {"services": {"mirror": {"cpus": 1, "pids_limit": 64}}},
    }


class TestWebserverWorkerLimits(unittest.TestCase):
    group_vars: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.group_vars = load_yaml(_WEBSERVER_VARS)

    def setUp(self) -> None:
        _reset_cache_for_tests()
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

    def test_proxy_connections_follow_the_proxy_alone(self) -> None:
        for scope in ({}, {"service_name": "mirror"}):
            with self.subTest(**scope):
                self.assertEqual(
                    self._render(
                        "{{ WEBSERVER_PROXY_WORKER_CONNECTIONS }}",
                        _applications(4),
                        **scope,
                    ),
                    "256",
                )

    def test_proxy_processes_follow_the_proxy_alone(self) -> None:
        for scope in ({}, {"service_name": "mirror"}):
            with self.subTest(**scope):
                self.assertEqual(
                    self._render(
                        "{{ WEBSERVER_PROXY_WORKER_PROCESSES }}",
                        _applications(4),
                        **scope,
                    ),
                    "4",
                )

    def test_a_sub_cpu_proxy_still_runs_one_worker(self) -> None:
        self.assertEqual(
            self._render("{{ WEBSERVER_PROXY_WORKER_PROCESSES }}", _applications(0.5)),
            "1",
        )

    def test_app_internal_limits_still_pair_with_the_play(self) -> None:
        applications = _applications(4)
        self.assertEqual(
            self._render("{{ WEBSERVER_WORKER_CONNECTIONS }}", applications), "64"
        )
        self.assertEqual(
            self._render("{{ WEBSERVER_WORKER_PROCESSES }}", applications), "1"
        )

    def test_shared_proxy_nginx_conf_uses_the_proxy_limits(self) -> None:
        worker_lines = [
            line.strip()
            for line in read_text(str(_NGINX_CONF)).splitlines()
            if line.strip().startswith("worker_")
        ]
        rendered = self._render("\n".join(worker_lines), _applications(4))
        self.assertEqual(
            rendered.splitlines(), ["worker_processes 4;", "worker_connections 256;"]
        )


if __name__ == "__main__":
    unittest.main()

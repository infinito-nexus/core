from __future__ import annotations

import unittest

from jinja2 import Environment, Undefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

VARS = PROJECT_ROOT / "roles" / "web-app-semaphore" / ROLE_FILE_VARS_MAIN
GUARDED = {
    "web-app-checkmk": (
        "MONITOR_CHECKMK_API",
        "MONITOR_CHECKMK_SITE",
        "MONITOR_TLS_WARN_DAYS",
        "MONITOR_TLS_CRIT_DAYS",
    ),
    "web-app-prometheus": ("MONITOR_PROMETHEUS_DIR", "MONITOR_PROMETHEUS_RELOAD_URL"),
}
FLAGS = ("SEMAPHORE_MONITORING_CHECKMK", "SEMAPHORE_MONITORING_PROMETHEUS")


class Value(str):
    __slots__ = ()
    source = "/srv/instances"


def render(groups, absent):
    """Args:
        groups: the inventory groups the render sees.
        absent: the roles whose lookups must not run.

    Returns:
        Every ``MONITOR_*`` value of ``SEMAPHORE_WORKSPACES_VARIABLES``, rendered.
    """
    values = load_yaml_any(str(VARS))

    def lookup(_kind, role, *_args, **_kwargs):
        if role in absent:
            raise AssertionError(f"lookup of the absent {role}")
        return Value("x")

    environment = Environment(
        undefined=Undefined, autoescape=select_autoescape(default_for_string=False)
    )
    environment.filters["bool"] = lambda value: (
        str(value).lower() in ("true", "1", "yes")
    )
    context = {"groups": groups, "lookup": lookup}
    for flag in (*FLAGS, "SEMAPHORE_MONITORING_CHECKMK_SITE"):
        context[flag] = environment.from_string(values[flag]).render(context)
    return {
        key: environment.from_string(str(value)).render(context)
        for key, value in values["SEMAPHORE_WORKSPACES_VARIABLES"].items()
        if key.startswith("MONITOR_")
    }


class TestThePlatformWithoutMonitoring(unittest.TestCase):
    def test_no_checkmk_or_prometheus_lookup_runs_without_them(self) -> None:
        for groups in ({}, {"web-app-checkmk": [], "web-app-prometheus": []}):
            with self.subTest(groups=groups):
                rendered = render(groups, set(GUARDED))
                for keys in GUARDED.values():
                    for key in keys:
                        self.assertEqual(rendered[key], "")

    def test_control_the_lookups_run_where_both_are_deployed(self) -> None:
        rendered = render(
            {"web-app-checkmk": ["a"], "web-app-prometheus": ["a"]}, set()
        )
        for keys in GUARDED.values():
            for key in keys:
                with self.subTest(key=key):
                    self.assertNotEqual(rendered[key], "")

    def test_one_role_alone_guards_only_the_other(self) -> None:
        rendered = render({"web-app-checkmk": ["a"]}, {"web-app-prometheus"})
        self.assertNotEqual(rendered["MONITOR_CHECKMK_SITE"], "")
        self.assertEqual(rendered["MONITOR_PROMETHEUS_DIR"], "")


if __name__ == "__main__":
    unittest.main()

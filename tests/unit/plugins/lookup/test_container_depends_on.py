from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.container_depends_on import LookupModule
from utils.cache.yaml import load_yaml_str


def _apps(*, db_enabled=False, db_shared=False, redis=False, oauth2=False):
    return {
        "app": {
            "services": {
                "postgres": {"enabled": db_enabled, "shared": db_shared},
                "redis": {"enabled": redis},
                "oauth2": {"enabled": oauth2},
            }
        },
        "svc-db-postgres": {"services": {"postgres": {"name": "postgres-central"}}},
    }


def _run(app_id, applications, **kwargs):
    with patch(
        "plugins.lookup.container_depends_on.get_merged_applications",
        return_value=applications,
    ):
        return LookupModule().run([app_id], variables={}, **kwargs)


def _parse(rendered: str) -> dict[str, Any]:
    if not rendered.strip():
        return {}
    data = load_yaml_str(rendered.lstrip())
    return data if isinstance(data, dict) else {}


class TestContainerDependsOnLookup(unittest.TestCase):
    def test_missing_or_extra_terms_raise(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([], variables={})
        with self.assertRaises(AnsibleError):
            LookupModule().run(["a", "b"], variables={})
        with self.assertRaises(AnsibleError):
            LookupModule().run([""], variables={})

    def test_unknown_application_raises(self):
        with self.assertRaises(AnsibleError):
            _run("missing", _apps())

    def test_no_db_no_redis_returns_empty_string(self):
        out = _run("app", _apps())[0]
        self.assertEqual(out, "")

    def test_local_db_only_emits_database(self):
        out = _run("app", _apps(db_enabled=True, db_shared=False))[0]
        self.assertEqual(
            _parse(out),
            {"depends_on": {"database": {"condition": "service_healthy"}}},
        )

    def test_shared_db_does_not_emit_database(self):
        out = _run("app", _apps(db_enabled=True, db_shared=True))[0]
        self.assertEqual(out, "")

    def test_redis_only_emits_redis(self):
        out = _run("app", _apps(redis=True))[0]
        self.assertEqual(
            _parse(out),
            {"depends_on": {"redis": {"condition": "service_healthy"}}},
        )

    def test_oauth2_implies_redis(self):
        out = _run("app", _apps(oauth2=True))[0]
        self.assertIn("redis", _parse(out)["depends_on"])

    def test_local_db_plus_redis(self):
        out = _run("app", _apps(db_enabled=True, db_shared=False, redis=True))[0]
        self.assertEqual(
            _parse(out),
            {
                "depends_on": {
                    "database": {"condition": "service_healthy"},
                    "redis": {"condition": "service_healthy"},
                }
            },
        )

    def test_extra_entries_appended(self):
        out = _run(
            "app",
            _apps(db_enabled=True),
            extra={"init": {"condition": "service_completed_successfully"}},
        )[0]
        body = _parse(out)["depends_on"]
        self.assertEqual(body["init"]["condition"], "service_completed_successfully")

    def test_extra_only_emits_depends_on_block(self):
        out = _run(
            "app",
            _apps(),
            extra={"resolver": {"condition": "service_started"}},
        )[0]
        self.assertEqual(
            _parse(out),
            {"depends_on": {"resolver": {"condition": "service_started"}}},
        )

    def test_indent_default_four_spaces(self):
        out = _run("app", _apps(redis=True))[0]
        self.assertTrue(out.startswith("    depends_on:"))

    def test_indent_zero(self):
        out = _run("app", _apps(redis=True), indent=0)[0]
        self.assertTrue(out.startswith("depends_on:"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from unittest import TestCase, main, mock

from ansible.errors import AnsibleError

from utils.security.suppressions import Suppression, SuppressionError

from . import PROJECT_ROOT


def _load_module():
    path = (
        PROJECT_ROOT
        / "roles"
        / "sys-ctl-hlth-runtime"
        / "lookup_plugins"
        / "cve_suppressions.py"
    )
    spec = importlib.util.spec_from_file_location("cve_suppressions_lookup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()
UNTIL = dt.date(2026, 12, 31)
DECLARED = {
    "web-app-checkmk": {
        "checkmk": [
            Suppression("CVE-2026-1", None, UNTIL),
            Suppression(None, "2.4.0p39", UNTIL),
        ]
    },
    "sys-ctl-hlth-runtime": {
        "trivy": [Suppression("CVE-2026-2", None, UNTIL)],
        "runtime": [Suppression("CVE-2026-3", None, UNTIL)],
    },
}


def _declared(declared):
    return lambda _roles_dir, role: declared.get(role, {})


class TestCollect(TestCase):
    def _collect(self, roles, declared=DECLARED):
        with mock.patch.object(
            MODULE, "role_suppressions", side_effect=_declared(declared)
        ):
            return MODULE.collect(roles)

    def test_a_role_is_keyed_by_its_stack_name(self):
        self.assertEqual(
            self._collect(["web-app-checkmk"])["containers"],
            {
                "checkmk": {
                    "checkmk": [
                        {"id": "CVE-2026-1", "image_tag": None, "until": "2026-12-31"},
                        {"id": None, "image_tag": "2.4.0p39", "until": "2026-12-31"},
                    ]
                }
            },
        )

    def test_a_role_without_suppressions_is_left_out(self):
        self.assertEqual(self._collect(["web-app-nextcloud"])["containers"], {})

    def test_host_suppressions_come_from_the_engine_entries_only(self):
        self.assertEqual(
            self._collect([])["host"],
            {"trivy": [{"id": "CVE-2026-2", "image_tag": None, "until": "2026-12-31"}]},
        )

    def test_an_engine_image_tag_entry_covers_its_image_not_the_host(self):
        declared = {
            "sys-ctl-hlth-runtime": {
                "grype": [
                    Suppression("CVE-2026-2", None, UNTIL),
                    Suppression(None, "v0.121.0", UNTIL),
                ]
            }
        }
        collected = self._collect(["sys-ctl-hlth-runtime"], declared)
        self.assertEqual(
            (
                [entry["image_tag"] for entry in collected["host"]["grype"]],
                [
                    entry["image_tag"]
                    for entries in collected["containers"].values()
                    for entry in entries["grype"]
                ],
            ),
            ([None], [None, "v0.121.0"]),
        )


class TestLookup(TestCase):
    def test_group_names_must_be_a_list(self):
        with self.assertRaises(AnsibleError):
            MODULE.LookupModule().run([], {}, group_names="web-app-checkmk")

    def test_a_malformed_suppression_fails_the_lookup(self):
        with (
            mock.patch.object(
                MODULE, "role_suppressions", side_effect=SuppressionError("bad")
            ),
            self.assertRaisesRegex(AnsibleError, "bad"),
        ):
            MODULE.LookupModule().run([], {}, group_names=["web-app-checkmk"])


if __name__ == "__main__":
    main()

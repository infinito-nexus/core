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
    "web-app-checkmk": {"checkmk": [Suppression("CVE-2026-1", UNTIL)]},
    "sys-ctl-hlth-runtime": {
        "trivy": [Suppression("CVE-2026-2", UNTIL)],
        "runtime": [Suppression("CVE-2026-3", UNTIL)],
    },
}


def _declared(_roles_dir, role):
    return DECLARED.get(role, {})


class TestCollect(TestCase):
    def _collect(self, roles):
        with mock.patch.object(MODULE, "role_suppressions", side_effect=_declared):
            return MODULE.collect(roles)

    def test_a_role_is_keyed_by_its_stack_name(self):
        self.assertEqual(
            self._collect(["web-app-checkmk"])["containers"],
            {"checkmk": {"checkmk": [{"id": "CVE-2026-1", "until": "2026-12-31"}]}},
        )

    def test_a_role_without_suppressions_is_left_out(self):
        self.assertEqual(self._collect(["web-app-nextcloud"])["containers"], {})

    def test_host_suppressions_come_from_the_engine_entries_only(self):
        self.assertEqual(
            self._collect([])["host"],
            {"trivy": [{"id": "CVE-2026-2", "until": "2026-12-31"}]},
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

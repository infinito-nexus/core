from __future__ import annotations

import re
import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

APP = "web-app-dashboard"
ROLE = PROJECT_ROOT / "roles" / APP
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
SCHEDULE = load_yaml_any(str(PROJECT_ROOT / "group_vars" / "all" / "07_schedule.yml"))


class _Config(LookupBase):
    def __init__(self, answers: dict):
        """Answer ``lookup('config', app, path)`` from a fixed mapping.

        Args:
            answers: the value per configuration path of the dashboard.
        """
        super().__init__()
        self._answers = answers

    def run(self, terms, variables=None, **kwargs):
        application_id, path = terms[0], terms[1]
        if application_id != APP:
            raise AssertionError(f"unexpected config lookup {terms}")
        return [self._answers[path]]


def _resolve(name: str, *, sso: bool, locks: bool, status: bool):
    """Template one dashboard variable with the given switches.

    Args:
        name: the variable of ``vars/main.yml``.
        sso: ``services.sso.enabled``.
        locks: ``services.dashboard.locks.enabled``.
        status: ``services.dashboard.status.enabled``.
    """
    answers = {
        "services.sso.enabled": sso,
        "services.dashboard.locks.enabled": locks,
        "services.dashboard.status.enabled": status,
    }
    real_get = lookup_loader.get

    def get(plugin, *args, **kwargs):
        if plugin == "config":
            return _Config(answers)
        return real_get(plugin, *args, **kwargs)

    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )
    templar = Templar(loader=DataLoader(), variables=declared)
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(declared[name])


class TestLockSwitch(unittest.TestCase):
    def test_locks_show_with_sso_and_the_switch_on(self):
        self.assertIs(
            _resolve("DASHBOARD_LOCKS_ENABLED", sso=True, locks=True, status=True),
            True,
        )

    def test_the_inventory_switch_turns_the_locks_off(self):
        self.assertIs(
            _resolve("DASHBOARD_LOCKS_ENABLED", sso=True, locks=False, status=True),
            False,
        )

    def test_without_sso_the_locks_are_off(self):
        self.assertIs(
            _resolve("DASHBOARD_LOCKS_ENABLED", sso=False, locks=True, status=True),
            False,
        )

    def test_both_switches_default_on(self):
        dashboard = SERVICES["dashboard"]
        self.assertIs(dashboard["locks"]["enabled"], True)
        self.assertIs(dashboard["status"]["enabled"], True)
        self.assertIs(dashboard["folders"], True)


class TestChipScript(unittest.TestCase):
    def test_chips_js_ships_while_one_chip_kind_is_on(self):
        for locks, status in ((True, False), (False, True), (True, True)):
            with self.subTest(locks=locks, status=status):
                self.assertEqual(
                    _resolve(
                        "DASHBOARD_JS_FILES", sso=True, locks=locks, status=status
                    ),
                    ["iframe.js", "chips.js", "oidc.js"],
                )

    def test_chips_js_stays_away_with_both_kinds_off(self):
        self.assertEqual(
            _resolve("DASHBOARD_JS_FILES", sso=True, locks=False, status=False),
            ["iframe.js", "oidc.js"],
        )
        self.assertEqual(
            _resolve("DASHBOARD_JS_FILES", sso=False, locks=True, status=False),
            ["iframe.js"],
        )


class TestStatusTiming(unittest.TestCase):
    def test_the_staleness_threshold_bridges_the_nightly_sweep_pause(self):
        first, last = (
            int(hour)
            for hour in re.fullmatch(
                r"(\d+)\.\.(\d+)", SCHEDULE["HOURS_SERVER_AWAKE"]
            ).groups()
        )
        nightly_gap = (24 - last + first) * 3600
        stale = SERVICES["dashboard"]["status"]["stale_after_seconds"]

        self.assertIn(
            "{{ HOURS_SERVER_AWAKE }}:00:00", SCHEDULE["SYS_SCHEDULE_HEALTH_NGINX"]
        )
        self.assertGreater(stale, nightly_gap)

    def test_the_poll_is_shorter_than_the_hourly_sweep(self):
        poll = SERVICES["dashboard"]["status"]["poll_seconds"]

        self.assertGreater(poll, 0)
        self.assertLess(poll, 3600)

    def test_a_new_application_keeps_its_badge_for_fourteen_days(self):
        self.assertEqual(SERVICES["dashboard"]["new_days"], 14)


if __name__ == "__main__":
    unittest.main()

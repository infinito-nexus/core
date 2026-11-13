from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "web-app-matomo" / "tasks" / "07_config.yml"
ROLE_IPS = ["203.0.113.5", "2001:db8::1"]


def _tasks() -> list[dict]:
    return load_yaml_any(str(TASKS), default_if_missing=[])


def _stored(value) -> dict:
    return {"stdout": json.dumps({"value": value}, separators=(",", ":"))}


def _body(setter: str, ips, user_agents) -> dict[str, str]:
    task = next(
        task
        for task in _tasks()
        if setter in task.get("ansible.builtin.shell", {}).get("stdin", "")
    )
    templar = Templar(
        loader=DataLoader(),
        variables={
            "MATOMO_EXCLUDED_IPS": ROLE_IPS,
            "matomo_token_value": "token",
            "matomo_exclusions_stored": {
                "results": [_stored(ips), _stored(user_agents)]
            },
        },
    )
    rendered = templar.template(
        _trust_as_template(task["ansible.builtin.shell"]["stdin"])
    )
    return {key: values[0] for key, values in parse_qs(rendered).items()}


class TestExclusionsKeepAdminEntries(unittest.TestCase):
    def test_the_stored_lists_are_read_before_they_are_written(self):
        stdins = [
            task.get("ansible.builtin.shell", {}).get("stdin", "") for task in _tasks()
        ]
        read = next(
            index
            for index, stdin in enumerate(stdins)
            if "'SitesManager.' ~ item" in stdin
        )
        self.assertEqual(
            ["getExcludedIpsGlobal", "getExcludedUserAgentsGlobal"],
            _tasks()[read]["loop"],
        )
        self.assertLess(
            read,
            min(
                index
                for index, stdin in enumerate(stdins)
                if "SitesManager.setGlobalExcluded" in stdin
            ),
        )

    def test_an_ip_an_admin_added_survives_and_the_missing_role_ips_join_it(self):
        body = _body("setGlobalExcludedIps", "198.51.100.7,203.0.113.5", False)
        self.assertEqual("198.51.100.7,203.0.113.5,2001:db8::1", body["excludedIps"])

    def test_a_user_agent_an_admin_added_survives_next_to_the_csp_checker(self):
        body = _body("setGlobalExcludedUserAgents", False, "Pingdom")
        self.assertEqual("Pingdom,CSP-CheckerBot", body["excludedUserAgents"])

    def test_a_fresh_install_gets_the_role_entries_only(self):
        self.assertEqual(
            ",".join(ROLE_IPS),
            _body("setGlobalExcludedIps", False, False)["excludedIps"],
        )
        self.assertEqual(
            "CSP-CheckerBot",
            _body("setGlobalExcludedUserAgents", "", "")["excludedUserAgents"],
        )

    def test_a_list_that_holds_every_role_entry_stays_unchanged(self):
        body = _body("setGlobalExcludedIps", "2001:db8::1,203.0.113.5", False)
        self.assertEqual("2001:db8::1,203.0.113.5", body["excludedIps"])


if __name__ == "__main__":
    unittest.main()

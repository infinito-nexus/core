import importlib.util
import json
import re
import unittest

from . import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "wazuh_docker",
    PROJECT_ROOT / "roles" / "web-app-wazuh" / "filter_plugins" / "wazuh_docker.py",
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

COMPOSE = """
services:
  redis:
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
  database:
    healthcheck:
      test: [ "CMD", "sh", "-c", "/usr/bin/mariadb --user=$$MYSQL_USER --execute 'SHOW DATABASES;'" ]
  worker:
    healthcheck:
      test:
      - CMD-SHELL
      - test ! -e /var/www/storage/.docker.init || (php artisan horizon:status | grep running)
  plain:
    healthcheck:
      test: curl -f http://localhost/ > /dev/null && echo ok
  off:
    healthcheck:
      disable: true
  none:
    healthcheck:
      test: ["NONE"]
  app:
    image: probe
"""

ENTITY = {
    "entity": "pixelfed",
    "role": "web-app-pixelfed",
    "docker": {
        "oom": 101096,
        "healthcheck": 101097,
        "swarm": 101098,
        "compose": 101099,
    },
}


class TestHealthcheckActions(unittest.TestCase):
    def test_actions_match_what_docker_reports(self):
        self.assertEqual(
            _module.wazuh_healthcheck_actions(COMPOSE),
            [
                "/bin/sh -c curl -f http://localhost/ > /dev/null && echo ok",
                "/bin/sh -c test ! -e /var/www/storage/.docker.init || (php artisan horizon:status | grep running)",
                "redis-cli ping",
                "sh -c /usr/bin/mariadb --user=$MYSQL_USER --execute 'SHOW DATABASES;'",
            ],
        )

    def test_compose_without_services_has_no_actions(self):
        self.assertEqual(_module.wazuh_healthcheck_actions("{}"), [])


class TestHealthcheckPattern(unittest.TestCase):
    def _matches(self, actions, action):
        pattern = (
            _module.wazuh_healthcheck_pattern(actions)
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
        )
        return re.search(pattern, action) is not None

    def test_exact_health_check_exec_matches(self):
        actions = _module.wazuh_healthcheck_actions(COMPOSE)
        for action in actions:
            for verb in ("exec_create", "exec_start"):
                with self.subTest(action=action, verb=verb):
                    self.assertTrue(self._matches(actions, f"{verb}: {action}"))

    def test_exec_die_matches(self):
        self.assertTrue(self._matches(["redis-cli ping"], "exec_die"))
        self.assertTrue(self._matches([], "exec_die"))

    def test_anything_else_does_not_match(self):
        actions = ["redis-cli ping"]
        for action in (
            "exec_start: redis-cli ping; id",
            "exec_start: sh",
            "exec_start: redis-cli",
            "start",
            "exec_detach: redis-cli ping",
        ):
            with self.subTest(action=action):
                self.assertFalse(self._matches(actions, action))

    def test_pattern_is_xml_escaped(self):
        pattern = _module.wazuh_healthcheck_pattern(["a > b && c < d"])
        self.assertNotRegex(pattern, r"[<>]|&(?!amp;|lt;|gt;)")


class TestDockerSamples(unittest.TestCase):
    def _samples(self, healthchecks):
        return _module.wazuh_docker_samples([ENTITY], healthchecks, 5, 7, 87903, 3)

    def test_samples_cover_every_attribution_rule(self):
        samples = self._samples({"pixelfed": ["redis-cli ping"]})
        expected_compose = {
            ("start", 101099, 5),
            ("die", 101099, 5),
            ("oom", 101096, 7),
            ("exec_start: sh", 101099, 5),
            ("exec_die", 101097, 0),
            ("exec_start: redis-cli ping", 101097, 0),
            ("exec_start: redis-cli ping; id", 101099, 5),
        }
        expected_swarm = {("start", 101098, 5), ("oom", 101096, 7)}
        compose, swarm = set(), set()
        for sample in samples:
            docker = json.loads(sample["line"])["docker"]
            labels = docker["Actor"]["Attributes"]
            entry = (docker["Action"], sample["rule"], sample["level"])
            if labels.get(_module.STACK_LABEL) == "pixelfed":
                swarm.add(entry)
            elif labels.get(_module.COMPOSE_LABEL) == "pixelfed":
                compose.add(entry)
            else:
                self.assertEqual((sample["rule"], sample["level"]), (87903, 3))
        self.assertEqual(compose, expected_compose)
        self.assertEqual(swarm, expected_swarm)
        self.assertTrue(all(s["role"] == "web-app-pixelfed" for s in samples))

    def test_app_without_health_checks_has_no_health_check_exec_sample(self):
        actions = [json.loads(s["line"])["docker"]["Action"] for s in self._samples({})]
        self.assertNotIn("exec_start: redis-cli ping", actions)
        self.assertIn("exec_die", actions)


if __name__ == "__main__":
    unittest.main()

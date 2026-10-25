import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml_str
from utils.roles import account_policy


def policy(limit, pattern, reachable):
    return {
        "username_max_length": limit,
        "username_pattern": pattern,
        "source": "https://example.org/src#L1",
        "agent_reachable": reachable,
    }


class TestAccountPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.roles = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, role, name, data):
        meta = self.roles / role / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / name).write_text(dump_yaml_str(data), encoding="utf-8")

    def test_limits_are_the_minimum_over_all_and_over_agent_reachable_roles(self):
        self.write("web-app-a", "account.yml", {"account_policy": policy(40, "[a-z]+", True)})
        self.write("web-app-b", "account.yml", {"account_policy": policy(15, "[a-z0-9]+", False)})
        self.write("web-app-c", "account.yml", {"account_policy": policy(20, "[a-z]+", True)})
        self.write("web-app-d", "services.yml", {"sso": {"enabled": True}})

        policies = account_policy.load_policies(self.roles)

        self.assertEqual(sorted(policies), ["web-app-a", "web-app-b", "web-app-c"])
        self.assertEqual(account_policy.username_max_length(policies), 15)
        self.assertEqual(account_policy.account_max_length(policies), 20)
        self.assertEqual(
            account_policy.username_patterns(policies), ["[a-z0-9]+", "[a-z]+"]
        )

    def test_sso_roles_skip_only_a_literally_disabled_sso(self):
        self.write("web-app-on", "services.yml", {"sso": {"enabled": True}})
        self.write("web-app-var", "services.yml", {"sso": {"enabled": "{{ x }}"}})
        self.write("web-app-off", "services.yml", {"sso": {"enabled": False}})
        self.write("web-app-none", "services.yml", {"app": {"enabled": True}})

        self.assertEqual(
            account_policy.sso_roles(self.roles), ["web-app-on", "web-app-var"]
        )


if __name__ == "__main__":
    unittest.main()

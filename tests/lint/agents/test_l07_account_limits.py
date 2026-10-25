"""L07: every role that signs users in through SSO declares its application's
username limit, accepted pattern, upstream source and whether an agent may hold
an account there; the agent naming constants equal the limits derived from
those declarations; web-app-bluesky grants an agent no account."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.agents import naming
from utils.cache.yaml import dump_yaml_str
from utils.roles import account_policy

ROLES_DIR = PROJECT_ROOT / "roles"
AGENT_SEPARATOR_AND_CODE = 5

AGENT_REACHABLE_APPS = (
    "web-app-decidim",
    "web-app-discourse",
    "web-app-gitea",
    "web-app-mastodon",
    "web-app-matrix",
    "web-app-nextcloud",
    "web-app-openproject",
    "web-app-zammad",
)
NO_AGENT_ACCOUNT_APPS = ("web-app-bluesky",)


def _policy_problems(role: str, policy: object) -> list[str]:
    if not isinstance(policy, dict):
        return [f"{role}: account_policy must be a mapping"]
    problems = [
        f"{role}: account_policy.{key} is missing"
        for key in account_policy.POLICY_KEYS
        if key not in policy
    ]
    limit = policy.get("username_max_length")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        problems.append(f"{role}: username_max_length must be a positive integer")
    pattern = policy.get("username_pattern")
    if not isinstance(pattern, str) or not pattern or pattern[0] == "^" or pattern[-1] == "$":
        problems.append(f"{role}: username_pattern must be an unanchored regex")
    else:
        try:
            re.compile(pattern)
        except re.error as error:
            problems.append(f"{role}: username_pattern does not compile: {error}")
    source = policy.get("source")
    if not isinstance(source, str) or not source.startswith("https://"):
        problems.append(f"{role}: source must be an https URL to the upstream evidence")
    if not isinstance(policy.get("agent_reachable"), bool):
        problems.append(f"{role}: agent_reachable must be a boolean")
    return problems


def check(roles_dir: Path, account_max_length: int, username_max_length: int) -> list[str]:
    """Return the problems with the account-policy declarations under roles_dir.

    Args:
        roles_dir: the Ansible roles tree to read.
        account_max_length: the agent ceiling the agent-reachable minimum must equal.
        username_max_length: the human ceiling the overall minimum must equal.
    """
    policies = account_policy.load_policies(roles_dir)
    problems = [
        f"{role}: signs users in through SSO but ships no meta/account.yml"
        for role in account_policy.sso_roles(roles_dir)
        if role not in policies
    ]
    for role, policy in policies.items():
        problems.extend(_policy_problems(role, policy))
    if problems:
        return problems

    derived_account = account_policy.account_max_length(policies)
    derived_username = account_policy.username_max_length(policies)
    if derived_account != account_max_length:
        problems.append(
            f"smallest agent-reachable username limit is {derived_account}, "
            f"not the agent account ceiling {account_max_length}"
        )
    if derived_username != username_max_length:
        problems.append(
            f"smallest username limit is {derived_username}, "
            f"not the human username ceiling {username_max_length}"
        )
    if derived_username + AGENT_SEPARATOR_AND_CODE > derived_account:
        problems.append(
            f"an agent name <code>0<owner> of {derived_username + AGENT_SEPARATOR_AND_CODE} "
            f"characters overflows the agent account ceiling {derived_account}"
        )

    for role in AGENT_REACHABLE_APPS:
        if role in policies and policies[role]["agent_reachable"] is not True:
            problems.append(f"{role}: must declare agent_reachable true")
    for role in NO_AGENT_ACCOUNT_APPS:
        if role in policies and policies[role]["agent_reachable"] is not False:
            problems.append(f"{role}: must declare agent_reachable false")
    return problems


class TestL07(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(
            check(
                ROLES_DIR, naming.IAM_ACCOUNT_MAX_LENGTH, naming.IAM_USERNAME_MAX_LENGTH
            ),
            [],
        )

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            meta = roles / "web-app-example" / "meta"
            meta.mkdir(parents=True)
            (meta / "services.yml").write_text(
                dump_yaml_str({"sso": {"enabled": True}}), encoding="utf-8"
            )
            self.assertNotEqual(check(roles, 20, 15), [])
            (meta / "account.yml").write_text(
                dump_yaml_str(
                    {
                        "account_policy": {
                            "username_max_length": 10,
                            "username_pattern": "^[a-z]+$",
                            "source": "TODO",
                            "agent_reachable": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(check(roles, 20, 15), [])


if __name__ == "__main__":
    unittest.main()

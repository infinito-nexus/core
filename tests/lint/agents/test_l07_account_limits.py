"""L07: every account-creating role declares its username length ceiling and
whether an agent may hold an account there; the global account ceiling equals
the smallest ceiling across agent-reachable roles; web-app-bluesky grants an
agent no account."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.cache.yaml import dump_yaml_str, load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_ACCOUNT

ROLES_DIR = PROJECT_ROOT / "roles"
GENERAL_VARS = PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"

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


def account_ceiling() -> int:
    """Return IAM_ACCOUNT_MAX_LENGTH from the global variables."""
    return int(load_yaml(str(GENERAL_VARS))["IAM_ACCOUNT_MAX_LENGTH"])


def _is_length(value: object) -> bool:
    """Return True when value is a real integer length (a bool is not one)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _account_policy(roles_dir: Path, role: str) -> object:
    """Return the account_policy block of a role, or None when the role ships
    no meta/account.yml."""
    path = roles_dir / role / ROLE_FILE_META_ACCOUNT
    if not path.is_file():
        return None
    data = load_yaml_any(str(path), default_if_missing={})
    if not isinstance(data, dict):
        return None
    return data.get("account_policy")


def check(roles_dir: Path, account_max_length: int) -> list[str]:
    """Return the problems with the account-policy declarations under roles_dir.

    Args:
        roles_dir: the Ansible roles tree to read.
        account_max_length: the ceiling the smallest agent-reachable
            username length must equal.
    """
    problems: list[str] = []
    reachable: list[int] = []

    role_dirs = (
        sorted(p.name for p in roles_dir.iterdir() if p.is_dir())
        if roles_dir.is_dir()
        else []
    )
    for role in role_dirs:
        policy = _account_policy(roles_dir, role)
        if policy is None:
            continue
        if not isinstance(policy, dict):
            problems.append(f"{role}: account_policy must be a mapping")
            continue
        limit = policy.get("username_max_length")
        agent = policy.get("agent_reachable")
        if not _is_length(limit):
            problems.append(f"{role}: username_max_length must be an integer")
        if not isinstance(agent, bool):
            problems.append(f"{role}: agent_reachable must be a boolean")
        if agent is True and _is_length(limit):
            reachable.append(limit)

    if reachable:
        smallest = min(reachable)
        if smallest != account_max_length:
            problems.append(
                f"smallest agent-reachable username ceiling is {smallest}, "
                f"not the global account ceiling {account_max_length}"
            )

    for role in AGENT_REACHABLE_APPS:
        if not (roles_dir / role).is_dir():
            continue
        policy = _account_policy(roles_dir, role)
        if not isinstance(policy, dict):
            problems.append(f"{role}: must declare account_policy")
        elif policy.get("agent_reachable") is not True:
            problems.append(f"{role}: must declare agent_reachable true")

    for role in NO_AGENT_ACCOUNT_APPS:
        if not (roles_dir / role).is_dir():
            continue
        policy = _account_policy(roles_dir, role)
        if not isinstance(policy, dict):
            problems.append(f"{role}: must declare account_policy")
        elif policy.get("agent_reachable") is not False:
            problems.append(f"{role}: must declare agent_reachable false")

    return problems


class TestL07(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROLES_DIR, account_ceiling()), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            meta = roles / "web-app-example" / "meta"
            meta.mkdir(parents=True)
            (meta / "account.yml").write_text(
                dump_yaml_str(
                    {
                        "account_policy": {
                            "username_max_length": 10,
                            "agent_reachable": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(check(roles, 20), [])


if __name__ == "__main__":
    unittest.main()

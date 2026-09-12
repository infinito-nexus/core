"""Lint: a sandboxed agent acts as its own non-privileged platform account.

The users machinery reserves a key per role, so ``hermes`` and ``openclaw``
exist as accounts whether or not anyone claims them. Claiming the key is what
turns a reservation into an identity the agent may authenticate as, and gives
the account its description and its mailbox.

Two relations per sandboxed role:

* it claims its own reserved user key in ``meta/users.yml``;
* the claimed account carries no role, because an agent employee is a standard
  user and never an administrator.

The password is deliberately not one of them. Provisioning gives every declared
account a stored password, and a role that needs a different alphabet says so
in its own ``meta/users.yml`` rather than carrying a second credential beside
the account it already owns.

Pointing an agent at an account that already exists stays possible: the
inventory ``users`` variable overrides the same key, which is the documented
override path and needs no change here.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: agent-identity`` in the head of the role's ``meta/users.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_META_USERS

from . import PROJECT_ROOT
from .test_sandboxed_no_host_socket import _sandboxed_roles

_RULE = "agent-identity"
_CREDENTIAL = "identity_password"


def _users_of(role: str) -> tuple[Mapping | None, list[str]]:
    path = PROJECT_ROOT / "roles" / role / ROLE_FILE_META_USERS
    if not path.is_file():
        return None, []
    data = load_yaml_any(str(path), default_if_missing={})
    lines = read_text(str(path)).splitlines()
    return (data if isinstance(data, Mapping) else None), lines


def _claimed_roles() -> list[str]:
    kept = []
    for role in sorted(_sandboxed_roles()):
        _users, lines = _users_of(role)
        if lines and is_suppressed_in_head(lines, _RULE):
            continue
        kept.append(role)
    return kept


class TestAgentIdentity(unittest.TestCase):
    def test_every_agent_claims_its_own_account(self) -> None:
        missing = []
        for role in _claimed_roles():
            users, _lines = _users_of(role)
            key = get_entity_name(role)
            if users is None or key not in users:
                missing.append(
                    f"{role}: does not claim the reserved user key '{key}' in "
                    f"{ROLE_FILE_META_USERS}, so the agent has no account of "
                    f"its own to act as"
                )
        self.assertEqual(
            [],
            missing,
            "sandboxed agent(s) without their own account:\n"
            + "\n".join(f"  - {m}" for m in missing),
        )

    def test_no_agent_account_carries_a_role(self) -> None:
        privileged = []
        for role in _claimed_roles():
            users, _lines = _users_of(role)
            entry = (users or {}).get(get_entity_name(role))
            if not isinstance(entry, Mapping):
                continue
            if entry.get("roles"):
                privileged.append(
                    f"{role}: its account declares roles {entry['roles']}; an "
                    f"agent employee is a standard user, never privileged"
                )
        self.assertEqual(
            [],
            privileged,
            "agent account(s) with privileges:\n"
            + "\n".join(f"  - {p}" for p in privileged),
        )

    def test_no_agent_carries_a_credential_beside_its_own_account(self) -> None:
        doubled = []
        for role in _claimed_roles():
            secrets = load_yaml_any(
                str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SECRETS),
                default_if_missing={},
            )
            credentials = (secrets or {}).get("credentials")
            if isinstance(credentials, Mapping) and _CREDENTIAL in credentials:
                doubled.append(
                    f"{role}: declares secrets.credentials.{_CREDENTIAL} beside "
                    f"the account it already owns; an account password belongs "
                    f"in {ROLE_FILE_META_USERS}, where provisioning stores it"
                )
        self.assertEqual(
            [],
            doubled,
            "agent(s) carrying a second credential for their own account:\n"
            + "\n".join(f"  - {d}" for d in doubled),
        )

    def test_the_scan_finds_agents(self) -> None:
        self.assertTrue(
            _claimed_roles(),
            "no sandboxed agent role found, so every rule here would pass "
            "vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()

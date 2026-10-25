"""Account-name rules for agents and humans.

The digit ``0`` is the agent separator and appears nowhere else in a name, so
an agent account is unambiguous: ``<code>0<suffix>`` with a four-character role
code and a suffix of the instance id or the owner's username. A human username
carries no ``0`` at all. This is the deterministic generator and validator the
provisioner and the lints use; it renames nothing.
"""

from __future__ import annotations

import re

IAM_ACCOUNT_MAX_LENGTH = 20
IAM_USERNAME_MAX_LENGTH = 15

_CODE = re.compile(r"^[a-z1-9]{4}$")
_SUFFIX = re.compile(rf"^[a-z1-9]{{1,{IAM_USERNAME_MAX_LENGTH}}}$")
_AGENT = re.compile(
    rf"^(?P<code>[a-z1-9]{{4}})0(?P<suffix>[a-z1-9]{{1,{IAM_USERNAME_MAX_LENGTH}}})$"
)
_HUMAN = re.compile(rf"^[a-z1-9]{{3,{IAM_USERNAME_MAX_LENGTH}}}$")


def agent_account_name(code: str, suffix: str) -> str:
    """Return the agent account name ``<code>0<suffix>``.

    Args:
        code: the four-character role code, from agents/codes.yml.
        suffix: the instance id (team agent) or owner username (user-started).

    Raises:
        ValueError: if code or suffix is malformed or the name overflows
            ``IAM_ACCOUNT_MAX_LENGTH``.
    """
    if not _CODE.match(code):
        raise ValueError(f"role code {code!r} is not four of [a-z1-9]")
    if not _SUFFIX.match(suffix):
        raise ValueError(
            f"suffix {suffix!r} is not [a-z1-9]{{1,{IAM_USERNAME_MAX_LENGTH}}}"
        )
    name = f"{code}0{suffix}"
    if len(name) > IAM_ACCOUNT_MAX_LENGTH:
        raise ValueError(f"name {name!r} exceeds {IAM_ACCOUNT_MAX_LENGTH}")
    return name


def is_agent_name(name: str) -> bool:
    """Return whether ``name`` is a valid agent account name: exactly one ``0``,
    at the separator, and within the length bound."""
    return (
        bool(_AGENT.match(name))
        and name.count("0") == 1
        and len(name) <= IAM_ACCOUNT_MAX_LENGTH
    )


def is_human_name(name: str) -> bool:
    """Return whether ``name`` is a valid human username: [a-z1-9]{3,15}, no
    ``0``."""
    return bool(_HUMAN.match(name))


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    _expect(agent_account_name("mant", "alice") == "mant0alice", "agent name not built")
    _expect(is_agent_name("mant0alice"), "valid agent name rejected")
    _expect(is_agent_name("cnsl0a1b2c3"), "valid agent name rejected")
    _expect(not is_agent_name("mant0al0ce"), "two zeros accepted")
    _expect(not is_agent_name("mant1alice"), "missing separator accepted")
    _expect(not is_agent_name("man0alice"), "three-char code accepted")
    _expect(not is_agent_name("mant0" + "x" * 16), "overflow accepted")
    _expect(is_human_name("alice"), "valid human name rejected")
    _expect(not is_human_name("al"), "two-char human accepted")
    _expect(not is_human_name("al0ce"), "human with 0 accepted")
    _expect(not is_human_name("alice-bot"), "hyphen accepted")
    for bad_code, suffix in [("mnt", "x"), ("mant", ""), ("ma0t", "x")]:
        try:
            agent_account_name(bad_code, suffix)
        except ValueError:
            continue
        raise AssertionError(f"expected {bad_code}/{suffix} to fail")
    print("agent naming self-check ok")


if __name__ == "__main__":
    _demo()

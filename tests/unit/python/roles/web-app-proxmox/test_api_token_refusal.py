from __future__ import annotations

import re
import unittest

from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVER

from ._render import ROLE, planted

AUTHORIZATION = "$http_authorization"
TOKEN = "ws-0a@pve!provision=00000000-0000-0000-0000-000000000000"
TOKEN_HEADERS = (
    f"PVEAPIToken={TOKEN}",
    f"PVEAPIToken {TOKEN}",
    f" PVEAPIToken={TOKEN}",
    f"Bearer opaque PVEAPIToken={TOKEN}",
    f"pveapitoken={TOKEN}",
)
OTHER_HEADERS = ("", "Bearer opaque", "Basic dXNlcjpwYXNz")
IF_BLOCK = re.compile(
    r"^[ \t]*if\s*\((?P<condition>[^)\n]*)\)\s*\{(?P<body>[^{}]*)\}", re.MULTILINE
)
CONDITION = re.compile(
    r'^(?P<variable>\$\w+)\s+(?P<operator>~\*?)\s+"?(?P<pattern>[^"]+?)"?$'
)
REFUSAL = re.compile(r"\breturn\s+403\s*;")


def extra_template() -> str:
    """Returns:
    The template the role's ``meta/server.yml`` hands svc-stack as the
    server-level extra of its default vhost, the public domain.
    """
    server = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVER), default_if_missing={})
    return server["vhosts"]["default"]["extra_template"]


def source() -> str:
    return read_text(str(ROLE / "templates" / extra_template()))


def rendered(text: str) -> str:
    """Args:
        text: the extra template's text, or a planted variant of it.

    Returns:
        The rendered nginx fragment svc-stack places in the server block.
    """
    environment = Environment(
        loader=DictLoader({"extra": text}),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        keep_trailing_newline=True,
    )
    return environment.get_template("extra").render()


def refusing_patterns(fragment: str) -> list[re.Pattern]:
    """Args:
        fragment: a rendered server-level nginx fragment.

    Returns:
        The pattern of every ``if`` outside any other block that tests the
        Authorization header and answers 403, compiled with the case rule of
        its operator.
    """
    patterns = []
    for block in IF_BLOCK.finditer(fragment):
        if fragment.count("{", 0, block.start()) != fragment.count(
            "}", 0, block.start()
        ):
            continue
        condition = CONDITION.match(block.group("condition").strip())
        if condition is None or condition.group("variable") != AUTHORIZATION:
            continue
        if not REFUSAL.search(block.group("body")):
            continue
        flags = re.IGNORECASE if condition.group("operator") == "~*" else 0
        patterns.append(re.compile(condition.group("pattern"), flags))
    return patterns


def refusal_findings(fragment: str) -> list[str]:
    """Args:
        fragment: a rendered server-level nginx fragment.

    Returns:
        Every token header the fragment lets through to the gate and every
        header without a token it refuses; empty when it refuses exactly the
        API tokens.
    """
    patterns = refusing_patterns(fragment)
    if not patterns:
        return ["no server-level rule answers 403 to an Authorization header"]
    findings = [
        f"the public vhost passes {header!r} on to the gate"
        for header in TOKEN_HEADERS
        if not any(pattern.search(header) for pattern in patterns)
    ]
    findings += [
        f"the public vhost refuses {header!r}, which carries no API token"
        for header in OTHER_HEADERS
        if any(pattern.search(header) for pattern in patterns)
    ]
    return findings


class TestThePublicVhostRefusesApiTokens(unittest.TestCase):
    def test_the_public_domain_refuses_every_api_token(self) -> None:
        self.assertEqual([], refusal_findings(rendered(source())))

    def test_negative_control_an_anchored_case_sensitive_match_fails(self) -> None:
        text = planted(source(), '~* "PVEAPIToken"', '~ "^PVEAPIToken="')
        self.assertNotEqual([], refusal_findings(rendered(text)))

    def test_negative_control_a_rule_inside_a_location_fails(self) -> None:
        text = f"location /api2/ {{\n{source()}}}\n"
        self.assertNotEqual([], refusal_findings(rendered(text)))

    def test_negative_control_a_challenge_instead_of_a_refusal_fails(self) -> None:
        text = planted(source(), "return 403;", "return 401;")
        self.assertNotEqual([], refusal_findings(rendered(text)))

    def test_negative_control_refusing_every_request_fails(self) -> None:
        text = planted(source(), '"PVEAPIToken"', '".*"')
        self.assertNotEqual([], refusal_findings(rendered(text)))

    def test_negative_control_another_header_fails(self) -> None:
        text = planted(source(), AUTHORIZATION, "$http_cookie")
        self.assertNotEqual([], refusal_findings(rendered(text)))


if __name__ == "__main__":
    unittest.main()

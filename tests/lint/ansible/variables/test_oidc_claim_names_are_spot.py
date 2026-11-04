"""Enforce that a renderable file reads an OIDC claim name from its constant.

``group_vars/all/11_oidc.yml`` declares the claim names once::

    ATTRIBUTES:
      USERNAME: "preferred_username"
      GIVEN_NAME: "given_name"

Every template, vars file and meta file is rendered with ``OIDC`` in scope and
must read ``OIDC.ATTRIBUTES.<KEY>`` instead of repeating the literal. A claim
name spelled a second time is a second place to change when an identity
provider is reconfigured, and the copies are what a grep for the provider's
own vocabulary will not find: ``username_claim``, ``userNameField``,
``DefaultUsernameClaim`` and ``SOCIAL_AUTH_OIDC_USERNAME_KEY`` are four names
for one value.

Only ``preferred_username`` is guarded. The sibling names are not distinctive
enough to carry a rule: ``email``, ``name``, ``locale`` and ``website`` are
ordinary words that also name unrelated configuration keys, and Keycloak's own
protocol mapper templates have to spell ``given_name`` and ``family_name`` to
define the claims in the first place.

Scope: the renderable surface, where the constant is reachable. A static
payload under ``roles/*/files/`` is deliberately out of scope: it is shipped
verbatim into a container and cannot read an Ansible variable, so its claim
name has to arrive through an environment variable or a rendered config, which
is a change to the role rather than to the literal. Tests are out of scope too,
because a fixture legitimately builds the value it asserts on.

Not a violation: a name that merely contains the claim as a substring, such as
nginx's ``$upstream_http_x_auth_request_preferred_username``, which is derived
from a header rather than naming the claim.

Suppress with ``# nocheck: oidc-claim-name-spot`` on the line or directly
above it.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "oidc-claim-name-spot"
_SOURCE = "group_vars/all/11_oidc.yml"
_GUARDED = {"preferred_username": "USERNAME"}
_SCOPES = ("templates/", "vars/", "defaults/", "meta/")


def _is_renderable(rel_path: str) -> bool:
    """Whether a repo-relative path is rendered with ``OIDC`` in scope.

    Args:
        rel_path: path relative to the project root.
    """
    if rel_path == _SOURCE:
        return False
    if rel_path.startswith("group_vars/"):
        return True
    parts = rel_path.split("/")
    if len(parts) < 4 or parts[0] != "roles":
        return False
    return any(f"{parts[2]}/".startswith(scope) for scope in _SCOPES)


def _offenders(rel_path: str, content: str) -> list[str]:
    """Return the hardcoded claim names of one renderable file.

    Args:
        rel_path: path relative to the project root.
        content: the file's text.
    """
    lines = content.splitlines()
    found: list[str] = []
    for claim, key in _GUARDED.items():
        pattern = re.compile(
            r"(?<![A-Za-z0-9_])" + re.escape(claim) + r"(?![A-Za-z0-9_])"
        )
        for index, line in enumerate(lines, start=1):
            if not pattern.search(line):
                continue
            if is_suppressed_at(lines, index, _RULE, mode="same-or-above"):
                continue
            found.append(f"{rel_path}:{index}: {claim} -> OIDC.ATTRIBUTES.{key}")
    return found


class TestOidcClaimNamesAreSpot(unittest.TestCase):
    def test_the_constant_still_declares_every_guarded_claim(self) -> None:
        declared = read_text(str(PROJECT_ROOT / _SOURCE))

        for claim, key in _GUARDED.items():
            self.assertIn(
                f'{key}: "{claim}"',
                declared,
                f"{_SOURCE} no longer declares {key}; this rule points at a "
                "constant that moved, so fix the rule before the call sites.",
            )

    def test_no_renderable_file_repeats_a_claim_name(self) -> None:
        offenders: list[str] = []
        for path in iter_project_files(extensions=(".yml", ".j2", ".yaml")):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            if not _is_renderable(rel):
                continue
            try:
                content = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if not any(claim in content for claim in _GUARDED):
                continue
            offenders.extend(_offenders(rel, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} renderable line(s) spell an OIDC claim name that "
            f"{_SOURCE} already declares:\n"
            f"{report}\n\n"
            "Read the constant instead, so the claim name exists once.\n"
            f"Suppress a genuine exception with `# nocheck: {_RULE}`.",
        )


class TestClaimDetection(unittest.TestCase):
    def test_a_bare_claim_is_reported(self) -> None:
        self.assertEqual(
            [
                "roles/x/templates/a.j2:1: preferred_username -> OIDC.ATTRIBUTES.USERNAME"
            ],
            _offenders("roles/x/templates/a.j2", 'userNameField: "preferred_username"'),
        )

    def test_reading_the_constant_is_accepted(self) -> None:
        self.assertEqual(
            [],
            _offenders(
                "roles/x/templates/a.j2",
                'userNameField: "{{ OIDC.ATTRIBUTES.USERNAME }}"',
            ),
        )

    def test_a_longer_identifier_is_not_a_claim(self) -> None:
        self.assertEqual(
            [],
            _offenders(
                "roles/x/templates/a.j2",
                "auth_request_set $u $upstream_http_x_auth_request_preferred_username;",
            ),
        )

    def test_a_nocheck_suppresses_it(self) -> None:
        self.assertEqual(
            [],
            _offenders(
                "roles/x/templates/a.j2",
                f'userNameField: "preferred_username" # nocheck: {_RULE} reason',
            ),
        )

    def test_a_static_payload_is_out_of_scope(self) -> None:
        self.assertFalse(_is_renderable("roles/x/files/shell/configure-auth.sh"))

    def test_a_template_is_in_scope(self) -> None:
        self.assertTrue(_is_renderable("roles/x/templates/casc.yaml.j2"))


if __name__ == "__main__":
    unittest.main()

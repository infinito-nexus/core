"""Unit tests for `utils.cache.users_placeholders`.

Covers both substitution helpers consumed by `get_merged_users`:

* `substitute_primary_domain_placeholder` — extracts the host part
  of `DOMAIN_PRIMARY` (supports URL form, host:port, sub-paths) and
  inlines it wherever the cached users dict carries the literal
  string `{{ DOMAIN_PRIMARY }}`.
* `substitute_scalar_placeholders` — resolves each scalar var in
  `_SCALAR_USER_PLACEHOLDERS` (currently `ORGANIZATION`,
  `SOFTWARE_NAME`) via templar best-effort and inlines its
  `{{ VAR }}` placeholder.

Ansible 2.19's TrustedAsTemplate gate leaves untagged Jinja
unrendered, so these helpers are the SPOT for resolving the small
set of placeholders embedded in `roles/user-*/meta/users.yml`.
"""

from __future__ import annotations

import unittest
from typing import Any

from utils.cache.users.placeholders import (
    _SCALAR_USER_PLACEHOLDERS,
    substitute_primary_domain_placeholder,
    substitute_scalar_placeholders,
)


class _StubTemplar:
    """Render `{{ VAR }}` against a `variables` dict, leave other
    expressions untouched. Mimics the best-effort templar used by
    the users cache without pulling Ansible into the unit test."""

    def __init__(self, variables: dict[str, Any]) -> None:
        self.available_variables = variables

    def template(self, value: Any, **_: Any) -> Any:
        if not isinstance(value, str):
            return value
        out = value
        for key, val in self.available_variables.items():
            out = out.replace(f"{{{{ {key} }}}}", str(val))
        return out


def _user_dict(**fields: Any) -> dict[str, Any]:
    return {"administrator": {"username": "admin", **fields}}


class TestSubstitutePrimaryDomainPlaceholder(unittest.TestCase):
    def test_inlines_plain_host(self) -> None:
        users = _user_dict(email="admin@{{ DOMAIN_PRIMARY }}")
        out = substitute_primary_domain_placeholder(
            users,
            {"DOMAIN_PRIMARY": "infinito.example"},
            templar=_StubTemplar({"DOMAIN_PRIMARY": "infinito.example"}),
        )
        self.assertEqual(out["administrator"]["email"], "admin@infinito.example")

    def test_extracts_host_from_url(self) -> None:
        users = _user_dict(email="admin@{{ DOMAIN_PRIMARY }}")
        out = substitute_primary_domain_placeholder(
            users,
            {"DOMAIN_PRIMARY": "https://infinito.example/path"},
            templar=_StubTemplar({"DOMAIN_PRIMARY": "https://infinito.example/path"}),
        )
        self.assertEqual(out["administrator"]["email"], "admin@infinito.example")

    def test_strips_port(self) -> None:
        users = _user_dict(email="admin@{{ DOMAIN_PRIMARY }}")
        out = substitute_primary_domain_placeholder(
            users,
            {"DOMAIN_PRIMARY": "infinito.example:8443"},
            templar=_StubTemplar({"DOMAIN_PRIMARY": "infinito.example:8443"}),
        )
        self.assertEqual(out["administrator"]["email"], "admin@infinito.example")

    def test_returns_unchanged_when_var_missing(self) -> None:
        users = _user_dict(email="admin@{{ DOMAIN_PRIMARY }}")
        out = substitute_primary_domain_placeholder(users, {}, templar=_StubTemplar({}))
        self.assertEqual(out["administrator"]["email"], "admin@{{ DOMAIN_PRIMARY }}")

    def test_returns_unchanged_when_var_empty(self) -> None:
        users = _user_dict(email="admin@{{ DOMAIN_PRIMARY }}")
        out = substitute_primary_domain_placeholder(
            users, {"DOMAIN_PRIMARY": "   "}, templar=_StubTemplar({})
        )
        self.assertEqual(out["administrator"]["email"], "admin@{{ DOMAIN_PRIMARY }}")

    def test_renders_jinja_in_raw_value(self) -> None:
        # raw DOMAIN_PRIMARY is itself Jinja that the templar must
        # resolve before inlining.
        users = _user_dict(email="admin@{{ DOMAIN_PRIMARY }}")
        out = substitute_primary_domain_placeholder(
            users,
            {
                "DOMAIN_PRIMARY": "{{ SOFTWARE_DOMAIN }}",
                "SOFTWARE_DOMAIN": "infinito.example",
            },
            templar=_StubTemplar(
                {
                    "DOMAIN_PRIMARY": "{{ SOFTWARE_DOMAIN }}",
                    "SOFTWARE_DOMAIN": "infinito.example",
                }
            ),
        )
        self.assertEqual(out["administrator"]["email"], "admin@infinito.example")

    def test_walks_nested_structures(self) -> None:
        users = {
            "administrator": {
                "username": "admin",
                "addresses": [
                    "admin@{{ DOMAIN_PRIMARY }}",
                    {"alt": "root@{{ DOMAIN_PRIMARY }}"},
                ],
                "primary": ("primary@{{ DOMAIN_PRIMARY }}",),
            }
        }
        out = substitute_primary_domain_placeholder(
            users,
            {"DOMAIN_PRIMARY": "infinito.example"},
            templar=_StubTemplar({"DOMAIN_PRIMARY": "infinito.example"}),
        )
        nested = out["administrator"]
        self.assertEqual(nested["addresses"][0], "admin@infinito.example")
        self.assertEqual(nested["addresses"][1]["alt"], "root@infinito.example")
        self.assertEqual(nested["primary"], ("primary@infinito.example",))


class TestSubstituteScalarPlaceholders(unittest.TestCase):
    def test_inlines_organization(self) -> None:
        users = _user_dict(lastname="{{ ORGANIZATION }}")
        out = substitute_scalar_placeholders(
            users,
            {"ORGANIZATION": "Infinito.Nexus"},
            templar=_StubTemplar({"ORGANIZATION": "Infinito.Nexus"}),
        )
        self.assertEqual(out["administrator"]["lastname"], "Infinito.Nexus")

    def test_inlines_software_name(self) -> None:
        users = _user_dict(description="Owner of {{ SOFTWARE_NAME }}")
        out = substitute_scalar_placeholders(
            users,
            {"SOFTWARE_NAME": "Infinito.Nexus"},
            templar=_StubTemplar({"SOFTWARE_NAME": "Infinito.Nexus"}),
        )
        self.assertEqual(out["administrator"]["description"], "Owner of Infinito.Nexus")

    def test_inlines_both_in_one_pass(self) -> None:
        users = _user_dict(
            lastname="{{ ORGANIZATION }}",
            description="{{ SOFTWARE_NAME }} operator",
        )
        out = substitute_scalar_placeholders(
            users,
            {"ORGANIZATION": "Infinito.Nexus", "SOFTWARE_NAME": "Infinito.Nexus"},
            templar=_StubTemplar(
                {"ORGANIZATION": "Infinito.Nexus", "SOFTWARE_NAME": "Infinito.Nexus"}
            ),
        )
        self.assertEqual(out["administrator"]["lastname"], "Infinito.Nexus")
        self.assertEqual(out["administrator"]["description"], "Infinito.Nexus operator")

    def test_resolves_jinja_in_raw_value(self) -> None:
        # ORGANIZATION is defined in group_vars as `{{ SOFTWARE_NAME }}`;
        # the helper must template the variable's own value before
        # inlining it into the users dict.
        users = _user_dict(lastname="{{ ORGANIZATION }}")
        out = substitute_scalar_placeholders(
            users,
            {
                "ORGANIZATION": "{{ SOFTWARE_NAME }}",
                "SOFTWARE_NAME": "Infinito.Nexus",
            },
            templar=_StubTemplar(
                {
                    "ORGANIZATION": "{{ SOFTWARE_NAME }}",
                    "SOFTWARE_NAME": "Infinito.Nexus",
                }
            ),
        )
        self.assertEqual(out["administrator"]["lastname"], "Infinito.Nexus")

    def test_returns_unchanged_when_var_is_empty(self) -> None:
        # Whitespace-only var: skip without inlining empty content.
        users = _user_dict(lastname="{{ ORGANIZATION }}")
        out = substitute_scalar_placeholders(
            users,
            {"ORGANIZATION": "   "},
            templar=_StubTemplar({"ORGANIZATION": "   "}),
        )
        self.assertEqual(out["administrator"]["lastname"], "{{ ORGANIZATION }}")

    def test_returns_unchanged_when_no_placeholders_in_variables(self) -> None:
        users = _user_dict(lastname="{{ ORGANIZATION }}")
        out = substitute_scalar_placeholders(users, {}, templar=_StubTemplar({}))
        self.assertEqual(out["administrator"]["lastname"], "{{ ORGANIZATION }}")

    def test_walks_nested_structures(self) -> None:
        users = {
            "administrator": {
                "tokens": {"web-app-matomo": "owned by {{ ORGANIZATION }}"},
                "aliases": ["{{ ORGANIZATION }}-admin", "ops"],
                "history": ("first: {{ SOFTWARE_NAME }}",),
            }
        }
        out = substitute_scalar_placeholders(
            users,
            {"ORGANIZATION": "Infinito.Nexus", "SOFTWARE_NAME": "Infinito.Nexus"},
            templar=_StubTemplar(
                {"ORGANIZATION": "Infinito.Nexus", "SOFTWARE_NAME": "Infinito.Nexus"}
            ),
        )
        nested = out["administrator"]
        self.assertEqual(nested["tokens"]["web-app-matomo"], "owned by Infinito.Nexus")
        self.assertEqual(nested["aliases"][0], "Infinito.Nexus-admin")
        self.assertEqual(nested["history"], ("first: Infinito.Nexus",))


class TestScalarPlaceholderSet(unittest.TestCase):
    def test_default_set_contains_known_keys(self) -> None:
        # Guardrail: extending the tuple is intentional, removing
        # an entry breaks existing user metas; pin the current set.
        self.assertEqual(
            set(_SCALAR_USER_PLACEHOLDERS), {"ORGANIZATION", "SOFTWARE_NAME"}
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

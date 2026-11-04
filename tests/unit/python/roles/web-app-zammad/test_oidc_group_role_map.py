from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_RBAC, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-zammad"
VARS = ROLE / ROLE_FILE_VARS_MAIN
RBAC = ROLE / ROLE_FILE_META_RBAC
NATIVE = ROLE / "files/ruby/apply/administrator.rb"
TEMPLATE = ROLE / "templates/zz/oidc/group_role_mapping.rb.j2"
GRANTS_KEY = "ZAMMAD_RBAC_ROLE_GRANTS"
MAP_KEY = "ZAMMAD_OIDC_GROUP_ROLE_MAP"
LDAP_MAP_KEY = "ZAMMAD_LDAP_GROUP_ROLE_MAP"
LDAP_APPLY = ROLE / "files/ruby/apply/ldap_source.rb"
ADMIN_ROLE = "administrator"
MACHINE_ROLES = {"mcp"}


def native_administrator_roles() -> list[str]:
    """Read the Zammad roles the password path grants the platform administrator.

    Returns:
        The role names of ``Role.where(name: %w[...])`` in ``administrator.rb``.
    """
    match = re.search(r"Role\.where\(name:\s*%w\[([^\]]*)\]\)", read_text(str(NATIVE)))
    if not match:
        raise AssertionError(
            f"{NATIVE} no longer grants its roles through Role.where(name: %w[...])"
        )
    return match.group(1).split()


def role_vars() -> dict:
    return load_yaml_str(read_text(str(VARS)))


def declared_rbac_roles() -> set[str]:
    return set(load_yaml_str(read_text(str(RBAC)))["roles"])


class TestOidcGroupRoleMap(unittest.TestCase):
    def test_the_administrator_group_grants_what_the_password_path_grants(self) -> None:
        self.assertCountEqual(
            role_vars()[GRANTS_KEY][ADMIN_ROLE],
            native_administrator_roles(),
            "Zammad's Admin role carries no ticket permission: an administrator who "
            "arrives through the identity provider and is not also an Agent loses the "
            "dashboard, the overviews and every ticket, while the same account signing "
            f"in with its password keeps them, because {NATIVE} grants Admin and Agent "
            "together",
        )

    def test_every_granted_role_resolves_its_group_path_through_the_lookup(
        self,
    ) -> None:
        variables = role_vars()
        expression = variables[MAP_KEY]
        self.assertIsInstance(
            expression,
            str,
            f"{VARS}: {MAP_KEY} must stay one Jinja expression. Ansible renders a "
            "mapping's values and leaves its keys alone, so a group path written as a "
            "mapping key reaches the Zammad initializer as its own '{{ ... }}' source "
            "text, matches no group Keycloak sends, and every account that signs in "
            "through the identity provider falls back to Customer",
        )
        self.assertRegex(
            expression,
            r"(?s)\A\{\{.*\}\}\Z",
            f"{VARS}: {MAP_KEY} must be the bare expression, with no character outside "
            "'{{' and '}}'. One stray leading or trailing space makes native templating "
            "hand over the Python repr of the mapping as a string; the Ruby side then "
            "indexes a String, String#[] answers with the matching substring instead of "
            "nil, no role resolves and the whole mapping becomes a silent no-op",
        )
        for role in variables[GRANTS_KEY]:
            self.assertIn(
                f"role='{role}'",
                expression,
                f"{VARS}: {MAP_KEY} grants nothing to the '{role}' group because it "
                f"never resolves its path, while {GRANTS_KEY} declares roles for it",
            )

    def test_every_granted_role_resolves_its_ldap_group_dn(self) -> None:
        variables = role_vars()
        expression = variables[LDAP_MAP_KEY]
        self.assertIsInstance(
            expression,
            str,
            f"{VARS}: {LDAP_MAP_KEY} must stay one Jinja expression, because Ansible "
            "leaves mapping keys untemplated and a literal '{{ ... }}' DN matches no group",
        )
        self.assertRegex(
            expression,
            r"(?s)\A\{\{.*\}\}\Z",
            f"{VARS}: {LDAP_MAP_KEY} must be the bare expression; a stray character turns "
            "the mapping into its Python repr and JSON.parse in ldap_source.rb then fails",
        )
        for role in variables[GRANTS_KEY]:
            self.assertIn(
                f"'-{role},' ~ LDAP.DN.OU.ROLES",
                expression,
                f"{VARS}: {LDAP_MAP_KEY} grants nothing to the '{role}' LDAP role group "
                f"while {GRANTS_KEY} declares roles for it, so the LDAP import hands that "
                "member the signup role and overrides the OIDC grant until the next sign-in",
            )

    def test_the_ldap_import_matches_what_net_ldap_hands_over(self) -> None:
        source = read_text(str(LDAP_APPLY))
        self.assertIn(
            "transform_keys(&:downcase)",
            source,
            "Net::LDAP::Entry downcases every attribute name and Zammad's FlatKeys mapping "
            "looks the source key up verbatim, so a camelCase key such as givenName or "
            "telephoneNumber never copies its value",
        )
        self.assertIn(
            "dn.downcase",
            source,
            "Ldap::Group#user_roles reads group_role_map[entry.dn.downcase], so a DN key "
            "kept in its original case maps no member onto any role",
        )
        self.assertIn(
            '"sigup_roles"',
            source,
            "with a group_role_map in place, unassigned_users 'skip_sync' skips or "
            "deactivates every directory user outside the mapped groups, which locks the "
            "customers of an open helpdesk out; Zammad spells the signup choice sigup_roles",
        )

    def test_every_rbac_role_a_person_can_hold_has_a_grant(self) -> None:
        self.assertEqual(
            declared_rbac_roles() - MACHINE_ROLES,
            set(role_vars()[GRANTS_KEY]),
            f"{RBAC} declares the RBAC roles this application hands out, and every one of "
            f"them that a person can hold needs a grant in {GRANTS_KEY}. An RBAC role "
            "without a grant maps to nothing, falls through to the Customer default and "
            f"demotes that account on every sign-in. {sorted(MACHINE_ROLES)} is excluded "
            "because the MCP agent is a password account converged by "
            "files/ruby/apply/mcp_bot.rb, never an account that arrives through the "
            "identity provider",
        )

    def test_a_patch_target_that_disappeared_stops_the_boot(self) -> None:
        source = read_text(str(TEMPLATE))
        reason = (
            "Zammad 7.1.2 defines only User.create_from_hash! (app/models/user.rb:312), "
            "so the earlier guard 'next unless User.respond_to?(...)' matched nothing, "
            "installed no patch at all and left every account that signed in through the "
            "identity provider on its signup role. A patch target that disappears must "
            "stop the boot, which the deploy's convergence wait turns into a failed CI "
            "deploy, instead of silently granting no role"
        )
        self.assertIn("Authorization.respond_to?(method_name)", source, reason)
        self.assertIn("raise ", source, reason)
        self.assertNotIn("User.respond_to?", source, reason)

    def test_an_unresolvable_grant_never_silently_downgrades(self) -> None:
        source = read_text(str(TEMPLATE))
        reason = (
            "Role.where without an active filter, or without checking that every mapped name "
            "resolved, hands back a subset: rename or deactivate Admin in the Zammad UI and "
            "the administrator is set to Agent alone, after which the idempotence guard "
            "reports the roles as already correct and never self-heals. A map that rendered "
            "as a String rather than a Hash is the same class of silent no-op, because "
            "String#[] answers with a substring instead of nil"
        )
        self.assertIn("Role.where(active: true,", source, reason)
        self.assertIn("missing.any?", source, reason)
        self.assertIn("is_a?(Hash)", source, reason)

    def test_the_profile_sync_requests_the_scopes_its_claims_need(self) -> None:
        variables = role_vars()
        scopes = variables["ZAMMAD_OIDC_SCOPE"].split()
        for scope in ("openid", "profile", "email", "phone", "address"):
            self.assertIn(
                scope,
                scopes,
                f"{VARS}: ZAMMAD_OIDC_SCOPE must request '{scope}'; Keycloak emits "
                "phone_number and address only for a client that asks for their optional "
                "scope, so the profile sync would never see them",
            )
        for field, claim in variables["ZAMMAD_OIDC_PROFILE_CLAIMS"].items():
            self.assertRegex(
                claim,
                r"\A\{\{ OIDC\.ATTRIBUTES\.[A-Z_]+ \}\}\Z",
                f"{VARS}: the claim of the Zammad field '{field}' must come from the "
                "OIDC.ATTRIBUTES SPOT",
            )

    def test_a_refused_profile_write_does_not_break_the_sign_in(self) -> None:
        source = read_text(str(TEMPLATE))
        for hook in ("find_from_hash", "create_from_hash"):
            body = source.split(f"define_method(:{hook})", 1)[1].split("end", 1)[0]
            self.assertIn(
                "_zammad_apply_oidc_profile!",
                body,
                f"{TEMPLATE}: {hook} must apply the OIDC profile, or a profile change in "
                "Keycloak reaches Zammad only through the LDAP import",
            )
        self.assertIn(
            "user.restore_attributes",
            source,
            "the profile sync runs inside SessionsController#create_omniauth; a refused "
            "save must be rescued and rolled back instead of answering the sign-in with 500",
        )

    def test_a_refused_role_write_does_not_break_the_sign_in(self) -> None:
        source = read_text(str(TEMPLATE))
        self.assertIn(
            "rescue StandardError",
            source,
            "Zammad guards its roles association (app/models/concerns/has_roles.rb:10-13): "
            "before_remove runs last_admin_check_by_role and before_add runs "
            "validate_agent_limit_by_role and validate_roles, each of which raises. The "
            "mapping runs inside SessionsController#create_omniauth, so an unrescued raise "
            "answers the sign-in with 500 and locks the account out instead of leaving it "
            "on the roles it already has",
        )


if __name__ == "__main__":
    unittest.main()

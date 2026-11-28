"""Multisite declares site-owner, serves its members' hosts and maps its group."""

from __future__ import annotations

import ast
import json
import re
import unittest

from ansible.plugins.filter.core import combine, flatten, to_bool, to_json
from ansible.plugins.test.core import match
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.applications import get_variants
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.domains.list import render_domain_value
from utils.domains.served import (
    ILLEGAL_LABELS,
    MEMBER_LABEL,
    MEMBER_LABEL_MAX,
    served_specs,
)
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

APPLICATION_ID = "web-app-wordpress"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
ROLE_VARS = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
GROUP_MAP_TEMPLATE = ROLE / "templates" / "rbac_group_map.json.j2"
MAPPER = ROLE / "files" / "mu-plugins" / "infinito-oidc-rbac-mapper.php"
SITE_OWNER = ROLE_VARS["WORDPRESS_RBAC_SITE_OWNER_ROLE"]
NETWORK_ADMIN = ROLE_VARS["WORDPRESS_RBAC_NETWORK_ADMIN_ROLE"]
SITE_ROLES = ROLE_VARS["WORDPRESS_RBAC_SITE_ROLES"]
GLOBAL_PREFIX = "global-"
PARENT = "user.blog.main.test"
SITES = ["blog.main.test", "biberblog.main.test", "biber.blog.main.test"]
ONION = "b5abfs7uwr23x6vbjxqjatyscpmkm6qkmkla7eyapdi4zpwtrz6o4nqd.onion"
ONION_SIBLINGS = [site.replace("main.test", ONION) for site in SITES]
CLEARNET_SERVED = {site: site for site in SITES}
TOR_ONLY_SERVED = dict(zip(SITES, ONION_SIBLINGS, strict=True))
OTHER_SERVED = {
    "name": "x.other.main.test",
    "application_id": "web-app-other",
    "members": ["x"],
}
DOMAINS_CONFIG = {
    "canonical": SITES,
    "served": [
        {"parent": "x.other.main.test", "role": "other"},
        {"parent": PARENT, "role": SITE_OWNER},
    ],
}
MANAGER_OPS = ROLE / "tasks" / "07_manager_ops.yml"
ONION_PARENT = PARENT.replace("main.test", ONION)
SERVED_RESOLVED = {
    "entries": [],
    "problems": ["web-app-wordpress: site-owner member 'harry.beaver' names no host"],
    "parents": [
        {
            "application_id": APPLICATION_ID,
            "role": "other",
            "parent": "x.other.main.test",
        },
        {"application_id": APPLICATION_ID, "role": SITE_OWNER, "parent": ONION_PARENT},
    ],
}


def _env() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(
        {
            "bool": to_bool,
            "combine": combine,
            "flatten": flatten,
            "to_json": to_json,
        }
    )
    env.tests["match"] = match
    return env


def _php_constant(name: str) -> str:
    found = re.search(rf"^const {name} = (.+);$", read_text(str(MAPPER)), re.MULTILINE)
    if found is None:
        raise AssertionError(f"the mapper declares no constant {name}")
    return found.group(1)


def _lookup(*terms: str, **kwargs: object) -> object:
    if terms == ("config", APPLICATION_ID, "domains") and not kwargs:
        return DOMAINS_CONFIG
    if terms == ("tls", APPLICATION_ID, "protocols.web") and not kwargs:
        return "https"
    raise AssertionError(
        f"the site-owner vars render an unexpected lookup{terms} {kwargs}"
    )


def _expression(name: str, **variables: object) -> object:
    source = ROLE_VARS[name].strip().removeprefix("{{").removesuffix("}}")
    return _env().compile_expression(source)(
        application_id=APPLICATION_ID,
        lookup=_lookup,
        WORDPRESS_RBAC_SITE_OWNER_ROLE=SITE_OWNER,
        **variables,
    )


def _multisite_variants() -> dict[int, dict]:
    variants = get_variants(roles_dir=PROJECT_ROOT / "roles")[APPLICATION_ID]
    return {
        index: variant
        for index, variant in enumerate(variants)
        if variant["services"]["wordpress"].get("multisite", {}).get("enabled")
    }


def _variant_rbac(multisite: bool) -> dict:
    """
    Args:
        multisite: whether the variant runs Multisite.

    Returns:
        WORDPRESS_RBAC_CONFIG of the first such variant: its merged rbac block.
    """
    for variant in get_variants(roles_dir=PROJECT_ROOT / "roles")[APPLICATION_ID]:
        enabled = variant["services"]["wordpress"].get("multisite", {}).get("enabled")
        if bool(enabled) == multisite:
            return variant["rbac"]
    raise AssertionError(f"no WordPress variant runs with multisite={multisite}")


def _group_map_lookup(served_sites: dict[str, str]):
    """
    Args:
        served_sites: canonical domain mapped to the site domain the node serves it on.

    Returns:
        The lookup the group map renders with: rbac_group_path and network_siblings.
    """

    def lookup(name: str, *terms: str, **kwargs: str) -> object:
        if name == "network_siblings":
            return [served_sites[terms[0]]]
        if name != "rbac_group_path":
            raise AssertionError(f"the group map renders an unexpected lookup {name}")
        tenant = [kwargs["tenant"]] if "tenant" in kwargs else []
        return "/".join(["roles", kwargs["application_id"], *tenant, kwargs["role"]])

    return lookup


def _group_map(
    multisite: bool, site_owner: bool, rbac: dict, served_sites: dict[str, str]
) -> dict:
    """
    Args:
        multisite: WORDPRESS_MULTISITE_ENABLED.
        site_owner: WORDPRESS_SITE_OWNER_ENABLED.
        rbac: WORDPRESS_RBAC_CONFIG, the merged rbac block of the deployed variant.
        served_sites: canonical domain mapped to its site domain on the node's
            canonical network.

    Returns:
        WORDPRESS_RBAC_GROUP_MAP as rbac_group_map.json.j2 renders it.
    """
    template = _env().from_string(read_text(str(GROUP_MAP_TEMPLATE)))
    rendered = template.render(
        application_id=APPLICATION_ID,
        lookup=_group_map_lookup(served_sites),
        WORDPRESS_MULTISITE_ENABLED=multisite,
        WORDPRESS_SITE_OWNER_ENABLED=site_owner,
        WORDPRESS_DOMAINS_CONFIG=DOMAINS_CONFIG,
        WORDPRESS_RBAC_CONFIG=rbac,
        WORDPRESS_RBAC_SITE_ROLES=SITE_ROLES,
        WORDPRESS_RBAC_NETWORK_ADMIN_ROLE=NETWORK_ADMIN,
        WORDPRESS_RBAC_SITE_OWNER_ROLE=SITE_OWNER,
    )
    return json.loads(rendered)


def _untenanted_site_roles(group_map: dict) -> dict:
    return {
        path: entry
        for path, entry in group_map.items()
        if "role" in entry and "tenant" not in entry
    }


class TestSiteOwnerVariant(unittest.TestCase):
    def test_every_multisite_variant_declares_site_owner_as_a_global_role(self):
        multisite = _multisite_variants()
        self.assertTrue(multisite, "no WordPress variant runs Multisite")
        for index, variant in multisite.items():
            with self.subTest(variant=index):
                role = variant["rbac"]["roles"][SITE_OWNER]
                self.assertEqual("global", role["scope"])

    def test_every_multisite_variant_serves_members_below_user_blog(self):
        for index, variant in _multisite_variants().items():
            with self.subTest(variant=index):
                rendered = render_domain_value(
                    variant["domains"], {"DOMAIN_PRIMARY": "main.test"}, "domains"
                )
                self.assertEqual(
                    ([(PARENT, SITE_OWNER)], []),
                    served_specs(APPLICATION_ID, {"domains": rendered}),
                )


class TestSiteOwnerGroupMap(unittest.TestCase):
    def test_the_multisite_map_names_only_the_network_sites_as_tenants(self):
        entries = _group_map(True, True, _variant_rbac(True), CLEARNET_SERVED).values()
        tenants = {entry["tenant"] for entry in entries if "tenant" in entry}
        self.assertEqual(set(SITES), tenants)

    def test_the_multisite_map_flags_exactly_the_site_owner_group(self):
        entries = _group_map(True, True, _variant_rbac(True), CLEARNET_SERVED).items()
        owners = [path for path, entry in entries if entry.get("site_owner")]
        self.assertEqual(["/roles/web-app-wordpress/site-owner"], owners)

    def test_the_site_owner_group_maps_no_wordpress_role_and_no_tenant(self):
        group_map = _group_map(True, True, _variant_rbac(True), CLEARNET_SERVED)
        self.assertEqual(
            {"site_owner": True}, group_map["/roles/web-app-wordpress/site-owner"]
        )

    def test_a_network_without_site_owners_carries_no_site_owner_group(self):
        entries = _group_map(True, False, _variant_rbac(True), CLEARNET_SERVED).values()
        self.assertFalse([entry for entry in entries if entry.get("site_owner")])

    def test_a_single_site_map_carries_no_site_owner_group(self):
        entries = _group_map(
            False, False, _variant_rbac(False), CLEARNET_SERVED
        ).values()
        self.assertFalse([entry for entry in entries if entry.get("site_owner")])


class TestGlobalSiteRoleGroupMap(unittest.TestCase):
    def test_every_multisite_variant_declares_a_global_role_per_site_role(self):
        multisite = _multisite_variants()
        self.assertTrue(multisite, "no WordPress variant runs Multisite")
        for index, variant in multisite.items():
            for role in SITE_ROLES:
                with self.subTest(variant=index, role=role):
                    declared = variant["rbac"]["roles"].get(GLOBAL_PREFIX + role)
                    self.assertEqual("global", (declared or {}).get("scope"))

    def test_the_multisite_map_grants_each_global_role_its_site_role_untenanted(self):
        group_map = _group_map(True, True, _variant_rbac(True), CLEARNET_SERVED)
        self.assertEqual(
            {
                f"/roles/{APPLICATION_ID}/{GLOBAL_PREFIX}{role}": {"role": role}
                for role in SITE_ROLES
            },
            _untenanted_site_roles(group_map),
        )

    def test_a_network_that_declares_no_global_role_maps_none(self):
        rbac = _variant_rbac(True)
        roles = {
            name: spec
            for name, spec in rbac["roles"].items()
            if not name.startswith(GLOBAL_PREFIX)
        }
        group_map = _group_map(True, True, {**rbac, "roles": roles}, CLEARNET_SERVED)
        self.assertEqual({}, _untenanted_site_roles(group_map))

    def test_a_single_site_maps_every_site_role_without_a_global_group(self):
        group_map = _group_map(False, False, _variant_rbac(False), CLEARNET_SERVED)
        self.assertEqual(
            {f"/roles/{APPLICATION_ID}/{role}": {"role": role} for role in SITE_ROLES},
            _untenanted_site_roles(group_map),
        )


def _per_site_groups(group_map: dict) -> dict:
    return {path: entry for path, entry in group_map.items() if "tenant" in entry}


class TestTorOnlyPerSiteGroupMap(unittest.TestCase):
    def test_a_tor_only_node_names_every_per_site_group_after_its_canonical_domain(
        self,
    ):
        group_map = _group_map(True, True, _variant_rbac(True), TOR_ONLY_SERVED)
        self.assertEqual(
            {
                f"/roles/{APPLICATION_ID}/{site}/{role}"
                for site in SITES
                for role in SITE_ROLES
            },
            set(_per_site_groups(group_map)),
        )

    def test_a_tor_only_node_grants_each_per_site_group_on_the_onion_site(self):
        group_map = _group_map(True, True, _variant_rbac(True), TOR_ONLY_SERVED)
        for site, onion_site in TOR_ONLY_SERVED.items():
            for role in SITE_ROLES:
                with self.subTest(site=site, role=role):
                    self.assertEqual(
                        {"role": role, "tenant": onion_site},
                        group_map[f"/roles/{APPLICATION_ID}/{site}/{role}"],
                    )

    def test_no_group_of_a_tor_only_node_is_named_after_an_onion_site(self):
        group_map = _group_map(True, True, _variant_rbac(True), TOR_ONLY_SERVED)
        self.assertEqual([], [path for path in group_map if ONION in path])


def _declarations(domains_config: dict) -> object:
    return _expression(
        "WORDPRESS_SITE_OWNER_DECLARATIONS", WORDPRESS_DOMAINS_CONFIG=domains_config
    )


def _enabled(multisite: bool, domains_config: dict) -> bool:
    return to_bool(
        _expression(
            "WORDPRESS_SITE_OWNER_ENABLED",
            WORDPRESS_MULTISITE_ENABLED=multisite,
            WORDPRESS_SITE_OWNER_DECLARATIONS=_declarations(domains_config),
        )
    )


class TestSiteOwnerVars(unittest.TestCase):
    def test_the_parent_is_the_served_parent_of_the_site_owner_declaration(self):
        parent = _expression(
            "WORDPRESS_SITE_OWNER_PARENT_DOMAIN",
            WORDPRESS_SITE_OWNER_RESOLVED=SERVED_RESOLVED,
        )
        self.assertEqual(ONION_PARENT, parent)

    def test_the_domains_config_comes_from_the_role_config(self):
        self.assertEqual(DOMAINS_CONFIG, _expression("WORDPRESS_DOMAINS_CONFIG"))

    def test_a_network_with_a_site_owner_declaration_enables_site_owners(self):
        self.assertTrue(_enabled(True, DOMAINS_CONFIG))

    def test_a_single_site_never_enables_site_owners(self):
        self.assertFalse(_enabled(False, DOMAINS_CONFIG))

    def test_a_network_without_a_served_list_enables_no_site_owners(self):
        self.assertFalse(_enabled(True, {"canonical": SITES}))

    def test_a_served_list_without_site_owner_enables_no_site_owners(self):
        other_only = {"canonical": SITES, "served": DOMAINS_CONFIG["served"][:1]}
        self.assertFalse(_enabled(True, other_only))

    def test_the_sweep_knows_every_member_once(self):
        served = [
            {"name": "*.user.blog.main.test", "members": ["biber", "mapache"]},
            {"name": "biber.user.blog.main.test", "members": ["biber"]},
        ]
        members = _expression(
            "WORDPRESS_SITE_OWNER_MEMBERS", WORDPRESS_SITE_OWNER_SERVED=served
        )
        self.assertEqual(["biber", "mapache"], members)

    def test_the_mapper_base_url_carries_the_role_scheme(self):
        template = _env().from_string(ROLE_VARS["WORDPRESS_SITE_OWNER_BASE_URL"])
        base_url = template.render(
            application_id=APPLICATION_ID,
            lookup=_lookup,
            WORDPRESS_SITE_OWNER_PARENT_DOMAIN=PARENT,
        )
        self.assertEqual("https://user.blog.main.test", base_url)

    def test_the_role_fronts_only_its_own_served_names(self):
        fact = [
            {"name": "*.user.blog.main.test", "application_id": APPLICATION_ID},
            OTHER_SERVED,
        ]
        served = _expression(
            "WORDPRESS_SITE_OWNER_SERVED", CURRENT_PLAY_SERVED_DOMAINS=fact
        )
        names = _expression(
            "WORDPRESS_SITE_OWNER_DOMAINS", WORDPRESS_SITE_OWNER_SERVED=served
        )
        self.assertEqual(["*.user.blog.main.test"], names)

    def test_a_wildcard_reserves_no_site_at_deploy(self):
        served = [{"name": "*.user.blog.main.test", "members": ["biber", "mapache"]}]
        logins = _expression(
            "WORDPRESS_SITE_OWNER_LOGINS", WORDPRESS_SITE_OWNER_SERVED=served
        )
        self.assertEqual([], logins)

    def test_every_member_served_by_name_gets_a_site_at_deploy(self):
        served = [
            {"name": "biber.user.blog.main.test", "members": ["biber"]},
            {"name": "mapache.user.blog.main.test", "members": ["mapache"]},
        ]
        logins = _expression(
            "WORDPRESS_SITE_OWNER_LOGINS", WORDPRESS_SITE_OWNER_SERVED=served
        )
        self.assertEqual(["biber", "mapache"], logins)


class TestSiteOwnerTaskOrder(unittest.TestCase):
    def test_the_deploy_reserves_sites_after_installing_the_mapper(self):
        includes = [
            task.get("include_tasks") for task in load_yaml_any(str(MANAGER_OPS))
        ]
        self.assertLess(
            includes.index("04_mu_plugins.yml"), includes.index("05_site_owners.yml")
        )


class TestMemberLabelParity(unittest.TestCase):
    def test_the_mapper_applies_the_member_label_rule_of_the_deploy(self):
        self.assertEqual(
            f"'/^(?:{MEMBER_LABEL.pattern})$/'",
            _php_constant(
                "INFINITO_RBAC_MEMBER_LABEL"  # nocheck: PHP constant of the mapper mu-plugin, not an env key
            ),
        )
        self.assertEqual(
            MEMBER_LABEL_MAX,
            int(
                _php_constant(
                    "INFINITO_RBAC_MEMBER_LABEL_MAX"  # nocheck: PHP constant of the mapper mu-plugin, not an env key
                )
            ),
        )
        illegal = _php_constant(
            "INFINITO_RBAC_ILLEGAL_LABELS"  # nocheck: PHP constant of the mapper mu-plugin, not an env key
        )
        self.assertEqual(
            ILLEGAL_LABELS,
            frozenset(ast.literal_eval(illegal.removeprefix("array"))),
        )


if __name__ == "__main__":
    unittest.main()

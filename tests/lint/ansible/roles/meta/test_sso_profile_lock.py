"""Lint guard: a profile field the SSO login overwrites is locked or written back.

A role declares its profile fields under ``services.sso.profile`` in
``meta/services.yml``:

* ``locked`` maps each field to the CSS selector of its input. The selector
  matches only while the field is locked for the account the form edits:
  every comma-separated part of it matches the role's ``MANAGED_MARKER``. The
  role's ``templates/javascript.js.j2`` includes ``SHARED_RENDERER``, which
  renders every match read-only with the translated warning as its hover title,
  so the role also enables ``services.javascript`` and proves the lock in
  ``ROLE_SPEC``, which ``ROLE_FILE_PLAYWRIGHT_SPEC`` requires. The role's own server side
  keeps the stored value when a request submits another one.
* ``languages`` lists the catalogue languages the renderer embeds: the UI
  languages the application serves, the source language included. Each
  language other than the source one translates the ``CATALOGUE_SOURCE``
  messages in its ``core`` catalogue.
* ``write_back`` lists the fields the application writes back to Keycloak or
  LDAP itself; only a role in ``WRITE_BACK``, with its evidence, may declare it.

Every role with a potentially enabled ``sso`` or ``ldap`` service is in exactly
one inventory list: ``OVERWRITTEN`` names the fields a treated role's login,
timer or deploy overwrites without writing them back, and each of them MUST
appear in ``locked`` or ``write_back``; ``NONE_NEEDED`` names the roles whose
inventory rows need no treatment; ``PENDING`` is the only exemption, the roles
not treated yet with the fields still open. ``PENDING`` only shrinks: its keys
are exactly ``PENDING_BASELINE``, a sorted tuple whose length is the literal
``PENDING_BASELINE_COUNT``, so exempting a role takes three visible edits, and
a role listed there alone that declares ``services.sso.profile`` fails until
its entry moves to ``OVERWRITTEN``.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.i18n.keyed import keyed_catalogue
from utils.i18n.languages import SOURCE_LANGUAGE, domain_languages, load_languages
from utils.roles.applications.services.sso import is_potentially_enabled
from utils.roles.custom import is_custom
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT, ROLES_DIR, load_role_meta

if TYPE_CHECKING:
    from pathlib import Path

SHARED_RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
CATALOGUE_SOURCE = "roles/sys-front-inj-javascript/files/profile_lock_i18n.yml"
CATALOGUE_CONTEXT = "profile_lock"
ROLE_SCRIPT = "templates/javascript.js.j2"
ROLE_SPEC = "files/playwright/test-profile-lock.js"
ROLE_SPEC_ENTRY = re.compile(
    r"^\s*require\(\s*[\"']\./test-profile-lock(?:\.js)?[\"']\s*\)", re.MULTILINE
)
PROFILE_KEYS = frozenset({"locked", "languages", "write_back"})

MANAGED_MARKER: dict[str, re.Pattern[str]] = {
    "web-app-grafana": re.compile(r"#[\w-]+:disabled"),
    "web-app-joomla": re.compile(r"#jform_\w+\[data-infinito-sso-locked\]"),
    "web-app-wordpress": re.compile(r"body\.infinito-sso-managed\s+\S.*"),
}

OVERWRITTEN: dict[str, frozenset[str]] = {
    "web-app-grafana": frozenset({"name", "email", "username"}),
    "web-app-joomla": frozenset(
        {
            "name",
            "username",
            "email",
            "language",
            "timezone",
            "phone",
            "address",
            "website",
        }
    ),
    "web-app-wordpress": frozenset(
        {"first_name", "last_name", "display_name", "email", "website", "language"}
    ),
}

FIELDS: frozenset[str] = frozenset().union(*OVERWRITTEN.values())

WRITE_BACK: dict[str, str] = {}

NONE_NEEDED: dict[str, str] = {
    "svc-ai-agent-broker": "API service, no profile UI",
    "svc-ai-agent-provisioner": "API service, no profile UI",
    "web-app-akaunting": "one seeded admin behind the gate",
    "web-app-dashboard": "no own accounts",
    "web-app-flowise": "one instance account behind the gate",
    "web-app-friendica": "LDAP read at account creation only",
    "web-app-fusiondirectory": "edits LDAP live",
    "web-app-hermes": "one shared dashboard account",
    "web-app-keycloak": "identity provider, the write-back target",
    "web-app-lam": "edits LDAP live",
    "web-app-mailu": "display name: end of life, no fixes",
    "web-app-map-animator": "no editable profile",
    "web-app-minio": "no user profile",
    "web-app-openbao": "no self-service profile",
    "web-app-openclaw": "identity per request from the header",
    "web-app-phpldapadmin": "edits LDAP live",
    "web-app-phpmyadmin": "gate only, no own profile",
    "web-app-pihole": "gate only, no own profile",
    "web-app-postmarks": "gate only, no own profile",
    "web-app-prometheus": "gate only, no own profile",
    "web-app-seaweedfs": "gate only, no own profile",
    "web-app-wazuh": "no stored profile",
    "web-app-workspace": "gate only, no own profile",
    "web-app-yourls": "gate only, no own profile",
    "web-svc-libretranslate": "gate only, no own profile",
    "web-svc-xmpp": "vCard read live from LDAP; avatar not overwritten",
}

PENDING: dict[str, str] = {
    "web-app-baserow": "first name; language; staff/superuser",
    "web-app-bigbluebutton": "name, email (upstream lock); role",
    "web-app-bluesky": "display name",
    "web-app-bookwyrm": "display name, language, time zone; groups, is_staff",
    "web-app-checkmk": "full name, email, pager; roles (upstream lock)",
    "web-app-decidim": "admin flag, user_manager",
    "web-app-discourse": "name, email (upstream lock); admin/moderator flags",
    "web-app-erpnext": "first name, last name; phone, mobile (LDAP); email (identity key); roles",
    "web-app-espocrm": "first/middle/last name, email, phone, gender; teams, user type",
    "web-app-fider": "role",
    "web-app-funkwhale": "email; first/last name, username (if editable); permission flags",
    "web-app-gitea": "full name, email (upstream lock); avatar (LDAP); admin/restricted flag",
    "web-app-gitlab": "name, email (upstream lock); admin/external flags",
    "web-app-grafana": "org role (upstream lock)",
    "web-app-homeassistant": "group, active flag",
    "web-app-jellyfin": "avatar (LDAP); administrator flag",
    "web-app-jenkins": "full name; email",
    "web-app-jitsi": "display name, email (meeting profile)",
    "web-app-kix": "contact name, email, login, title, phones, address, comment; roles",
    "web-app-litellm": "email; role",
    "web-app-listmonk": "role, status",
    "web-app-magento": "admin active state",
    "web-app-mastodon": "role",
    "web-app-matomo": "superuser, site access",
    "web-app-matrix": "display name",
    "web-app-mattermost": "first/last name, username (upstream lock); email (if editable); system_admin",
    "web-app-mediawiki": "real name, email, language, time zone (upstream lock); groups",
    "web-app-mobilizon": "role",
    "web-app-moodle": "name parts, email, phones, address, city, country, institution, department, description, ID number, URL, language, time zone, phonetic names (upstream lock); Manager, course creator, site admin",
    "web-app-n8n": "first/last name; email (identity key)",
    "web-app-nextcloud": "sociallogin display name, email, address, phone, website, admin group; LDAP display name, email, phone, website, organisation, role, biography, quota, avatar (upstream lock); LDAP address",
    "web-app-odoo": "name, email, phone, language, time zone; managed access groups",
    "web-app-opencloud": "role",
    "web-app-openproject": "first/last name, email, login; admin flag",
    "web-app-opentalk": "display name, names, email, avatar, groups (unverified)",
    "web-app-openwebui": "name; email; role, groups",
    "web-app-penpot": "full name; email (identity key)",
    "web-app-peertube": "role",
    "web-app-pgadmin": "role",
    "web-app-pixelfed": "is_admin",
    "web-app-pretix": "full name (if overwritten); email (upstream lock); SSO team membership, staff flag",
    "web-app-semaphore": "name, email; admin flag, project role",
    "web-app-shopware": "first/last name, email, locale, time zone, avatar; admin flag, ACL roles",
    "web-app-snipe-it": "first/last name, phone; email, job title, department, address, mobile, employee number; admin permission, permission group",
    "web-app-stalwart": "display name; group membership",
    "web-app-suitecrm": "first/last name; phone, mobile, title, department, address; is_admin",
    "web-app-taiga": "full name; email (LDAP); username (identity key); language, time zone (with the ref bump); superuser/staff",
    "web-app-weblate": "superuser, team membership",
    "web-app-wordpress": "role, blog membership, super admin",
    "web-app-xwiki": "first/last name, email, phone, address, website, language, time zone; company (LDAP); XWikiAdminGroup",
    "web-app-zammad": "first/last name, email, phone; address (API); mobile, department, note, login (LDAP); roles",
}

PENDING_BASELINE_COUNT = 51

PENDING_BASELINE: tuple[str, ...] = (
    "web-app-baserow",
    "web-app-bigbluebutton",
    "web-app-bluesky",
    "web-app-bookwyrm",
    "web-app-checkmk",
    "web-app-decidim",
    "web-app-discourse",
    "web-app-erpnext",
    "web-app-espocrm",
    "web-app-fider",
    "web-app-funkwhale",
    "web-app-gitea",
    "web-app-gitlab",
    "web-app-grafana",
    "web-app-homeassistant",
    "web-app-jellyfin",
    "web-app-jenkins",
    "web-app-jitsi",
    "web-app-kix",
    "web-app-listmonk",
    "web-app-litellm",
    "web-app-magento",
    "web-app-mastodon",
    "web-app-matomo",
    "web-app-matrix",
    "web-app-mattermost",
    "web-app-mediawiki",
    "web-app-mobilizon",
    "web-app-moodle",
    "web-app-n8n",
    "web-app-nextcloud",
    "web-app-odoo",
    "web-app-opencloud",
    "web-app-openproject",
    "web-app-opentalk",
    "web-app-openwebui",
    "web-app-peertube",
    "web-app-penpot",
    "web-app-pgadmin",
    "web-app-pixelfed",
    "web-app-pretix",
    "web-app-semaphore",
    "web-app-shopware",
    "web-app-snipe-it",
    "web-app-stalwart",
    "web-app-suitecrm",
    "web-app-taiga",
    "web-app-weblate",
    "web-app-wordpress",
    "web-app-xwiki",
    "web-app-zammad",
)


def _services(role: Path) -> dict[str, Any]:
    services = load_role_meta(role / ROLE_FILE_META_SERVICES)
    return services if isinstance(services, dict) else {}


def _block(services: dict[str, Any], key: str) -> dict[str, Any]:
    block = services.get(key)
    return block if isinstance(block, dict) else {}


def _identity_enabled(services: dict[str, Any]) -> bool:
    return any(
        "enabled" in _block(services, key)
        and is_potentially_enabled(_block(services, key)["enabled"])
        for key in ("sso", "ldap")
    )


def _profile(services: dict[str, Any]) -> Any:
    return _block(services, "sso").get("profile")


def _catalogue_languages() -> frozenset[str]:
    codes = domain_languages(load_languages(PROJECT_ROOT), "core")
    return frozenset({SOURCE_LANGUAGE, *codes})


def _schema_errors(role: str, profile: Any, catalogue: frozenset[str]) -> list[str]:
    where = f"{role}: services.sso.profile"
    if not isinstance(profile, dict) or not profile:
        return [f"{where} must be a mapping with `locked` and/or `write_back`"]
    errors = [
        f"{where}.{key} is not a known key; use {sorted(PROFILE_KEYS)}"
        for key in sorted(set(profile) - PROFILE_KEYS)
    ]
    locked = profile.get("locked", {})
    if not isinstance(locked, dict) or ("locked" in profile and not locked):
        errors.append(f"{where}.locked must map each field to a CSS selector")
        locked = {}
    for field, selector in locked.items():
        if field not in FIELDS:
            errors.append(
                f"{where}.locked.{field} is not a known field {sorted(FIELDS)}"
            )
        if not isinstance(selector, str) or not selector.strip():
            errors.append(f"{where}.locked.{field} must be a non-empty CSS selector")
    if locked:
        languages = profile.get("languages")
        if not isinstance(languages, list) or SOURCE_LANGUAGE not in languages:
            errors.append(
                f"{where}.languages must list the UI languages the application "
                f"serves, {SOURCE_LANGUAGE!r} included"
            )
        else:
            errors.extend(
                f"{where}.languages.{code} has no core catalogue"
                for code in languages
                if code not in catalogue
            )
    write_back = profile.get("write_back", [])
    if "write_back" in profile and role not in WRITE_BACK:
        errors.append(
            f"{where}.write_back needs an entry in WRITE_BACK naming the evidence "
            "that the application writes these fields back"
        )
    if not isinstance(write_back, list) or ("write_back" in profile and not write_back):
        errors.append(f"{where}.write_back must list the fields written back")
        write_back = []
    errors.extend(
        f"{where}.write_back.{field} is not a known field {sorted(FIELDS)}"
        for field in write_back
        if field not in FIELDS
    )
    errors.extend(
        f"{where}: {field} is both locked and written back"
        for field in sorted(set(locked) & set(write_back))
    )
    return errors


def _covered(profile: Any) -> set[str]:
    if not isinstance(profile, dict):
        return set()
    locked = profile.get("locked")
    write_back = profile.get("write_back")
    covered = set(locked) if isinstance(locked, dict) else set()
    if isinstance(write_back, list):
        covered |= set(write_back)
    return covered


def _locked(profile: Any) -> dict[str, Any]:
    locked = profile.get("locked") if isinstance(profile, dict) else None
    return locked if isinstance(locked, dict) else {}


def _unmarked_parts(role: str, locked: dict[str, Any]) -> list[str]:
    """Return every selector part of ``locked`` without the role's marker.

    Args:
        role: role name, a key of ``MANAGED_MARKER``.
        locked: ``services.sso.profile.locked`` of the role.

    Returns:
        ``field: part`` for every comma-separated part that does not fully
        match ``MANAGED_MARKER[role]``.
    """
    marker = MANAGED_MARKER[role]
    return [
        f"{field}: {part.strip()}"
        for field, selector in locked.items()
        if isinstance(selector, str)
        for part in selector.split(",")
        if not marker.fullmatch(part.strip())
    ]


def _translated_languages() -> frozenset[str]:
    source = load_yaml(PROJECT_ROOT / CATALOGUE_SOURCE)
    return frozenset(
        keyed_catalogue(PROJECT_ROOT, lambda key: f"{CATALOGUE_CONTEXT}:{key}", source)
    )


class TestSsoProfileLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.services = {
            role.name: _services(role)
            for role in sorted(ROLES_DIR.iterdir())
            if role.is_dir()
        }

    def test_every_profile_declaration_is_well_formed(self) -> None:
        catalogue = _catalogue_languages()
        errors = [
            error
            for role, services in self.services.items()
            if _profile(services) is not None
            for error in _schema_errors(role, _profile(services), catalogue)
        ]
        self.assertEqual([], errors)

    def test_every_overwritten_field_is_locked_or_written_back(self) -> None:
        missing = {
            role: sorted(fields - _covered(_profile(self.services.get(role, {}))))
            for role, fields in OVERWRITTEN.items()
        }
        missing = {role: fields for role, fields in missing.items() if fields}
        self.assertEqual(
            {},
            missing,
            "declare these fields under services.sso.profile.locked (field: CSS "
            "selector) or services.sso.profile.write_back in the role's "
            "meta/services.yml",
        )

    def test_every_role_with_sso_or_ldap_is_classified(self) -> None:
        unclassified = sorted(
            role
            for role, services in self.services.items()
            if not is_custom(role)
            and _identity_enabled(services)
            and role not in OVERWRITTEN
            and role not in PENDING
            and role not in NONE_NEEDED
        )
        self.assertEqual(
            [],
            unclassified,
            "classify the profile fields these roles let a user edit: lock or "
            "write back what the SSO login overwrites and add the role to "
            "OVERWRITTEN, or add it to NONE_NEEDED with the reason",
        )

    def test_every_listed_role_signs_in_through_keycloak_or_ldap(self) -> None:
        unknown = sorted(
            role
            for role in {*OVERWRITTEN, *PENDING, *NONE_NEEDED}
            if not _identity_enabled(self.services.get(role, {}))
        )
        self.assertEqual(
            [],
            unknown,
            "listed role(s) missing, or without a potentially enabled sso or ldap service",
        )

    def test_a_role_needing_no_treatment_is_neither_pending_nor_treated(self) -> None:
        self.assertEqual([], sorted(set(NONE_NEEDED) & {*OVERWRITTEN, *PENDING}))

    def test_the_pending_baseline_is_a_sorted_counted_tuple(self) -> None:
        self.assertEqual(tuple(sorted(set(PENDING_BASELINE))), PENDING_BASELINE)
        self.assertEqual(
            PENDING_BASELINE_COUNT,
            len(PENDING_BASELINE),
            "PENDING_BASELINE_COUNT is the literal length of PENDING_BASELINE",
        )

    def test_pending_never_grows(self) -> None:
        self.assertEqual(
            [],
            sorted(set(PENDING) - set(PENDING_BASELINE)),
            "PENDING only shrinks: treat the role instead of exempting it",
        )

    def test_a_role_leaving_pending_leaves_the_baseline(self) -> None:
        self.assertEqual(
            [],
            sorted(set(PENDING_BASELINE) - set(PENDING)),
            "drop these roles from PENDING_BASELINE and lower PENDING_BASELINE_COUNT, "
            "so the slot cannot exempt another role later",
        )

    def test_pending_only_shrinks(self) -> None:
        stale = sorted(
            role
            for role in set(PENDING) - set(OVERWRITTEN)
            if _profile(self.services.get(role, {})) is not None
        )
        self.assertEqual(
            [],
            stale,
            "these roles declare services.sso.profile: move their fields from "
            "PENDING into OVERWRITTEN",
        )

    def test_every_locking_role_renders_and_proves_the_shared_lock(self) -> None:
        errors = []
        for role, services in self.services.items():
            profile = _profile(services)
            if not isinstance(profile, dict) or "locked" not in profile:
                continue
            javascript = _block(services, "javascript")
            if "enabled" not in javascript or not is_potentially_enabled(
                javascript["enabled"]
            ):
                errors.append(f"{role}: services.javascript is not enabled")
            script = ROLES_DIR / role / ROLE_SCRIPT
            if not script.is_file() or SHARED_RENDERER not in read_text(str(script)):
                errors.append(
                    f"{role}: {ROLE_SCRIPT} does not include {SHARED_RENDERER}"
                )
            if not (ROLES_DIR / role / ROLE_SPEC).is_file():
                errors.append(f"{role}: {ROLE_SPEC} is missing")
            index = ROLES_DIR / role / ROLE_FILE_PLAYWRIGHT_SPEC
            if not index.is_file() or not ROLE_SPEC_ENTRY.search(read_text(str(index))):
                errors.append(
                    f"{role}: {ROLE_FILE_PLAYWRIGHT_SPEC} does not require"
                    " ./test-profile-lock"
                )
        self.assertEqual([], errors)

    def test_every_locked_selector_carries_the_managed_account_marker(self) -> None:
        errors = []
        for role, services in self.services.items():
            locked = _locked(_profile(services))
            if not locked:
                continue
            if role not in MANAGED_MARKER:
                errors.append(
                    f"{role}: add the marker its server renders for SSO accounts "
                    "only to MANAGED_MARKER"
                )
                continue
            errors.extend(f"{role}: {part}" for part in _unmarked_parts(role, locked))
        self.assertEqual(
            [],
            errors,
            "a locked selector must match the managed-account marker in every "
            "part, so it can never lock the form of an account the IdP does not own",
        )

    def test_every_declared_language_carries_the_translated_warning(self) -> None:
        translated = _translated_languages()
        missing = {}
        for role, services in self.services.items():
            profile = _profile(services)
            languages = profile.get("languages") if isinstance(profile, dict) else None
            if isinstance(languages, list) and set(languages) - translated:
                missing[role] = sorted(set(languages) - translated)
        self.assertEqual(
            {},
            missing,
            f"translate every message of {CATALOGUE_SOURCE} into these languages: "
            "make i18n-extract domain=core, then make i18n-translate",
        )

    def test_the_shared_renderer_exists(self) -> None:
        self.assertTrue((PROJECT_ROOT / SHARED_RENDERER).is_file())


if __name__ == "__main__":
    unittest.main()

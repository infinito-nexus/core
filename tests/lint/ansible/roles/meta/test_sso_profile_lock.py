"""Lint guard: a profile field the SSO login overwrites is locked or written back.

A role locks a profile field as a field of its ``meta/forms.yml`` whose
``source`` is ``sso.<ATTRIBUTE>``, a key of ``OIDC.ATTRIBUTES``; its ``selector``
matches only while the field is locked for the account the form edits: every
comma-separated part of it matches the role's ``MANAGED_MARKER``. The role's ``templates/javascript.js.j2``
includes ``SHARED_RENDERER``, which renders every match read-only with the
translated warning as its hover title, so the role also enables
``services.javascript`` and proves the lock in ``ROLE_SPEC``, which
``ROLE_FILE_PLAYWRIGHT_SPEC`` requires. The role's own server side keeps the
stored value when a request submits another one. The rest lives under
``services.sso.profile`` in ``meta/services.yml``:

* ``languages`` lists the catalogue languages the renderer embeds: the UI
  languages the application serves, the source language included. Each
  language other than the source one translates the ``CATALOGUE_SOURCE``
  messages in its ``core`` catalogue.
* ``write_back`` lists the fields the application writes back to Keycloak or
  LDAP itself; only a role in ``WRITE_BACK``, with its evidence, may declare it.
* ``overwritten`` lists the fields the role's login, timer or deploy
  overwrites without writing them back, and ``none_needed`` states why no
  field needs treatment; either one classifies the role in its own meta,
  ``none_needed`` alone.
* ``marker`` is the regular expression of the role's ``MANAGED_MARKER``, for
  a role whose marker is not listed there.

Every role with a potentially enabled ``sso`` or ``ldap`` service, a custom
``roles/web-app-cst-*`` role included, is classified exactly once: in one
inventory list of this file or by its own ``overwritten`` or ``none_needed``.
``OVERWRITTEN`` names the fields a treated role's login, timer or deploy
overwrites without writing them back, and each of them, like each field of a
role's own ``overwritten``, MUST be an ``sso.<ATTRIBUTE>`` field or appear in
``write_back``;
``NONE_NEEDED`` names the roles whose inventory rows need no treatment;
``PENDING`` is the only exemption, the roles not treated yet with the fields
still open. A custom role ships from its own repository, so it classifies
itself in the ``meta/services.yml`` of that repository. ``PENDING`` only
shrinks: its keys are exactly ``PENDING_BASELINE``, a sorted tuple whose length
is the literal ``PENDING_BASELINE_COUNT``, so exempting a role takes three
visible edits, and a role listed there alone that declares
``services.sso.profile`` fails until its entry moves to ``OVERWRITTEN``.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.i18n.keyed import keyed_catalogue
from utils.i18n.languages import SOURCE_LANGUAGE, domain_languages, load_languages
from utils.roles.applications import sso_fields
from utils.roles.applications.services.sso import is_potentially_enabled
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_PLAYWRIGHT_SPEC,
)

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
PROFILE_KEYS = frozenset(
    {"languages", "write_back", "overwritten", "none_needed", "marker"}
)
MOVED_KEY = "locked"
SELF_CLASSIFYING_KEYS = frozenset({"overwritten", "none_needed"})

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
    "web-app-proxmox": "gate only, no own profile",
    "web-app-seaweedfs": "gate only, no own profile",
    "web-app-wazuh": "no stored profile",
    "web-app-workspace": "gate only, no own profile",
    "web-app-worldmonitor": "gate only, no own profile",
    "web-app-yourls": "gate only, no own profile",
    "web-svc-access-request": "identity per request from the gate, no own profile",
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


def _forms(role: Path) -> dict[str, Any]:
    if not (role / ROLE_FILE_META_FORMS).is_file():
        return {}
    forms = load_role_meta(role / ROLE_FILE_META_FORMS)
    return forms if isinstance(forms, dict) else {}


def _locked(forms: Any) -> dict[str, Any]:
    return sso_fields.selectors(forms) if isinstance(forms, dict) else {}


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


def _own_overwritten(profile: Any) -> frozenset[str]:
    overwritten = profile.get("overwritten") if isinstance(profile, dict) else None
    if not isinstance(overwritten, list):
        return frozenset()
    return frozenset(field for field in overwritten if isinstance(field, str))


def _self_classified(services: dict[str, Any]) -> bool:
    profile = _profile(services)
    return isinstance(profile, dict) and bool(SELF_CLASSIFYING_KEYS & set(profile))


def _listed(role: str) -> bool:
    return role in OVERWRITTEN or role in PENDING or role in NONE_NEEDED


def _self_classification_errors(where: str, profile: dict[str, Any]) -> list[str]:
    errors = []
    if "none_needed" in profile:
        reason = profile["none_needed"]
        if not isinstance(reason, str) or not reason.strip():
            errors.append(
                f"{where}.none_needed must state why no profile field needs treatment"
            )
        errors.extend(
            f"{where}.none_needed excludes `{key}`"
            for key in sorted((set(profile) & PROFILE_KEYS) - {"none_needed"})
        )
    if "overwritten" in profile:
        overwritten = profile["overwritten"]
        if (
            not isinstance(overwritten, list)
            or not overwritten
            or not all(
                isinstance(field, str) and field.strip() for field in overwritten
            )
        ):
            errors.append(
                f"{where}.overwritten must list the fields the login, a timer or a "
                "deploy overwrites without writing them back"
            )
    return errors


def _marker_errors(
    role: str, where: str, profile: dict[str, Any], locked: dict[str, Any]
) -> list[str]:
    if "marker" not in profile:
        return []
    errors = []
    if role in MANAGED_MARKER:
        errors.append(f"{where}.marker duplicates MANAGED_MARKER[{role!r}]; keep one")
    if not locked:
        errors.append(
            f"{where}.marker needs the sso.<ATTRIBUTE> fields of {ROLE_FILE_META_FORMS}, "
            "the selectors it checks"
        )
    marker = profile["marker"]
    if not isinstance(marker, str) or not marker.strip():
        errors.append(f"{where}.marker must be a non-empty regular expression")
        return errors
    try:
        re.compile(marker)
    except re.error as error:
        errors.append(f"{where}.marker is no regular expression: {error}")
    return errors


def _schema_errors(
    role: str, profile: Any, catalogue: frozenset[str], locked: dict[str, Any]
) -> list[str]:
    where = f"{role}: services.sso.profile"
    if not isinstance(profile, dict) or not profile:
        return [f"{where} must be a non-empty mapping of {sorted(PROFILE_KEYS)}"]
    errors = [
        f"{where}.{MOVED_KEY} moved to {ROLE_FILE_META_FORMS}: declare each field "
        "there with source sso.<ATTRIBUTE>, a key of OIDC.ATTRIBUTES"
        if key == MOVED_KEY
        else f"{where}.{key} is not a known key; use {sorted(PROFILE_KEYS)}"
        for key in sorted(set(profile) - PROFILE_KEYS)
    ]
    errors.extend(_self_classification_errors(where, profile))
    errors.extend(_marker_errors(role, where, profile, locked))
    known = FIELDS | _own_overwritten(profile)
    errors.extend(
        f"{role}: {ROLE_FILE_META_FORMS} locks {field}, which is not a known field "
        f"{sorted(known)}"
        for field in locked
        if field not in known
    )
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
        f"{where}.write_back.{field} is not a known field {sorted(known)}"
        for field in write_back
        if field not in known
    )
    errors.extend(
        f"{where}: {field} is both locked and written back"
        for field in sorted(set(locked) & set(write_back))
    )
    return errors


def _covered(profile: Any, locked: dict[str, Any]) -> set[str]:
    covered = set(locked)
    write_back = profile.get("write_back") if isinstance(profile, dict) else None
    if isinstance(write_back, list):
        covered |= set(write_back)
    return covered


def _marker(role: str, profile: Any) -> re.Pattern[str] | None:
    """Return the managed-account marker the locked selectors of *role* match.

    Args:
        role: role name.
        profile: ``services.sso.profile`` of the role.

    Returns:
        ``MANAGED_MARKER[role]``, else the compiled ``profile.marker``, else
        ``None`` when the role declares no valid marker.
    """
    if role in MANAGED_MARKER:
        return MANAGED_MARKER[role]
    marker = profile.get("marker") if isinstance(profile, dict) else None
    if not isinstance(marker, str) or not marker.strip():
        return None
    try:
        return re.compile(marker)
    except re.error:
        return None


def _unmarked_parts(marker: re.Pattern[str], locked: dict[str, Any]) -> list[str]:
    """Return every selector part of ``locked`` without the role's marker.

    Args:
        marker: the role's managed-account marker, see ``_marker``.
        locked: the selector of each ``sso.<ATTRIBUTE>`` field of the role.

    Returns:
        ``field: part`` for every comma-separated part that does not fully
        match *marker*.
    """
    return [
        f"{field}: {part.strip()}"
        for field, selector in locked.items()
        if isinstance(selector, str)
        for part in selector.split(",")
        if not marker.fullmatch(part.strip())
    ]


def schema_errors(
    services_by_role: dict[str, dict[str, Any]],
    forms_by_role: dict[str, Any] | None = None,
) -> list[str]:
    """Return the findings of every declared ``services.sso.profile``.

    Args:
        services_by_role: role name mapped to its parsed ``meta/services.yml``.
        forms_by_role: role name mapped to its parsed ``meta/forms.yml``.
    """
    catalogue = _catalogue_languages()
    forms_by_role = forms_by_role or {}
    return [
        error
        for role, services in services_by_role.items()
        if _profile(services) is not None or _locked(forms_by_role.get(role))
        for error in _schema_errors(
            role, _profile(services), catalogue, _locked(forms_by_role.get(role))
        )
    ]


def unclassified_roles(services_by_role: dict[str, dict[str, Any]]) -> list[str]:
    """Return the roles with ``sso`` or ``ldap`` that no source classifies.

    Args:
        services_by_role: role name mapped to its parsed ``meta/services.yml``.

    Returns:
        The sorted roles with a potentially enabled ``sso`` or ``ldap``
        service that are in no inventory list and declare neither
        ``overwritten`` nor ``none_needed``.
    """
    return sorted(
        role
        for role, services in services_by_role.items()
        if _identity_enabled(services)
        and not _listed(role)
        and not _self_classified(services)
    )


def doubly_classified_roles(services_by_role: dict[str, dict[str, Any]]) -> list[str]:
    """Return the roles classified in an inventory list and in their own meta.

    Args:
        services_by_role: role name mapped to its parsed ``meta/services.yml``.
    """
    return sorted(
        role
        for role, services in services_by_role.items()
        if _listed(role) and _self_classified(services)
    )


def uncovered_fields(
    services_by_role: dict[str, dict[str, Any]],
    forms_by_role: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Return the overwritten fields each role neither locks nor writes back.

    Args:
        services_by_role: role name mapped to its parsed ``meta/services.yml``.
        forms_by_role: role name mapped to its parsed ``meta/forms.yml``.

    Returns:
        Role mapped to the sorted fields of ``OVERWRITTEN`` and of its own
        ``overwritten`` that are neither an ``sso.<ATTRIBUTE>`` field nor in
        ``write_back``; roles without such a field are left out.
    """
    forms_by_role = forms_by_role or {}
    inventory = {
        role: OVERWRITTEN.get(role, frozenset())
        | _own_overwritten(_profile(services_by_role.get(role, {})))
        for role in {*OVERWRITTEN, *services_by_role}
    }
    missing = {
        role: sorted(
            fields
            - _covered(
                _profile(services_by_role.get(role, {})),
                _locked(forms_by_role.get(role)),
            )
        )
        for role, fields in inventory.items()
    }
    return {role: fields for role, fields in sorted(missing.items()) if fields}


def marker_errors(
    services_by_role: dict[str, dict[str, Any]],
    forms_by_role: dict[str, Any] | None = None,
) -> list[str]:
    """Return the locked selectors that can match an account the IdP does not own.

    Args:
        services_by_role: role name mapped to its parsed ``meta/services.yml``.
        forms_by_role: role name mapped to its parsed ``meta/forms.yml``.

    Returns:
        One entry per locking role without a valid marker and per selector
        part its marker does not fully match.
    """
    forms_by_role = forms_by_role or {}
    errors = []
    for role, services in services_by_role.items():
        profile = _profile(services)
        locked = _locked(forms_by_role.get(role))
        if not locked:
            continue
        marker = _marker(role, profile)
        if marker is None:
            errors.append(
                f"{role}: declare the marker its server renders for SSO accounts "
                "only in MANAGED_MARKER or as services.sso.profile.marker"
            )
            continue
        errors.extend(f"{role}: {part}" for part in _unmarked_parts(marker, locked))
    return errors


def _translated_languages() -> frozenset[str]:
    source = load_yaml(PROJECT_ROOT / CATALOGUE_SOURCE)
    return frozenset(
        keyed_catalogue(
            PROJECT_ROOT,
            lambda key: f"{CATALOGUE_CONTEXT}:{key}",
            source,
            PROJECT_ROOT,
            "core",
        )
    )


class TestSsoProfileLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.services = {
            role.name: _services(role)
            for role in sorted(ROLES_DIR.iterdir())
            if role.is_dir()
        }
        cls.forms = {
            role.name: _forms(role)
            for role in sorted(ROLES_DIR.iterdir())
            if role.is_dir()
        }

    def test_every_profile_declaration_is_well_formed(self) -> None:
        self.assertEqual([], schema_errors(self.services, self.forms))

    def test_every_overwritten_field_is_locked_or_written_back(self) -> None:
        self.assertEqual(
            {},
            uncovered_fields(self.services, self.forms),
            "declare these fields in the role's meta/forms.yml with source "
            "sso.<ATTRIBUTE>, or under services.sso.profile.write_back in its "
            "meta/services.yml",
        )

    def test_every_role_with_sso_or_ldap_is_classified(self) -> None:
        self.assertEqual(
            [],
            unclassified_roles(self.services),
            "classify the profile fields these roles let a user edit: lock or "
            "write back what the SSO login overwrites and add the role to "
            "OVERWRITTEN, or add it to NONE_NEEDED with the reason; a custom "
            "roles/web-app-cst-* role declares services.sso.profile.overwritten "
            "or services.sso.profile.none_needed in the meta/services.yml of its "
            "source repository instead",
        )

    def test_no_role_is_classified_twice(self) -> None:
        self.assertEqual(
            [],
            doubly_classified_roles(self.services),
            "these roles are in an inventory list of this file and declare "
            "services.sso.profile.overwritten or none_needed; keep one",
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
            if not _locked(self.forms.get(role)):
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
        self.assertEqual(
            [],
            marker_errors(self.services, self.forms),
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

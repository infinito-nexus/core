from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/web-app-baserow/files/sso/infinito_sso.py"
DOMAIN = default_domain_primary()
HOSTNAME = f"baserow.{DOMAIN}"
BOOTSTRAP_EMAIL = f"platformadmin@{DOMAIN}"
SSO_ON = {
    "PROXY_HEADER_SSO": "true",
    "PROXY_HEADER_SSO_BOOTSTRAP_ADMIN_EMAIL": BOOTSTRAP_EMAIL,
}
IDENTITY = {
    "username": "alice",
    "email": f"alice@baserow.{DOMAIN}",
    "name": "Alice Smith",
    "is_admin": False,
    "language": None,
}


class _FakeQ:
    def __init__(self, **terms):
        self.terms = [terms] if terms else []

    def __or__(self, other):
        combined = _FakeQ()
        combined.terms = self.terms + other.terms
        return combined


class _FakeAPIView:
    @classmethod
    def as_view(cls, **initkwargs):
        return cls


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _Http404Error(Exception):
    pass


class _PermissionDeniedError(Exception):
    pass


def _normalize_email_address(email):
    return str(email).strip().lower()


def _modules(spec):
    created = {}
    for name, attributes in spec.items():
        module = ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        created[name] = module
    for name, module in created.items():
        parent, _, leaf = name.rpartition(".")
        if parent in created:
            setattr(created[parent], leaf, module)
    return created


def _load_module(hostname=HOSTNAME):
    stubs = _modules(
        {
            "baserow": {},
            "baserow.api": {},
            "baserow.api.user": {},
            "baserow.api.user.serializers": {
                "log_in_user": MagicMock(name="log_in_user")
            },
            "baserow.core": {},
            "baserow.core.models": {
                "WORKSPACE_USER_PERMISSION_ADMIN": "ADMIN",
                "UserProfile": MagicMock(name="UserProfile"),
                "Workspace": MagicMock(name="Workspace"),
                "WorkspaceUser": MagicMock(name="WorkspaceUser"),
            },
            "baserow.core.user": {},
            "baserow.core.user.handler": {"UserHandler": MagicMock(name="UserHandler")},
            "baserow.core.user.utils": {
                "normalize_email_address": _normalize_email_address
            },
            "baserow.infinito_sso_subject": {},
            "baserow.infinito_sso_subject.models": {
                "SsoSubject": MagicMock(name="SsoSubject")
            },
            "django": {},
            "django.conf": {
                "settings": SimpleNamespace(
                    PUBLIC_WEB_FRONTEND_HOSTNAME=hostname, LANGUAGE_CODE="en"
                )
            },
            "django.contrib": {},
            "django.contrib.auth": {
                "get_user_model": MagicMock(return_value=MagicMock(name="User"))
            },
            "django.core": {},
            "django.core.exceptions": {"PermissionDenied": _PermissionDeniedError},
            "django.db": {"transaction": SimpleNamespace(atomic=lambda func: func)},
            "django.db.models": {"Q": _FakeQ},
            "django.http": {"Http404": _Http404Error},
            "django.shortcuts": {"redirect": MagicMock(name="redirect")},
            "django.urls": {"path": MagicMock(name="path")},
            "rest_framework": {},
            "rest_framework.permissions": {"AllowAny": object()},
            "rest_framework.response": {"Response": _FakeResponse},
            "rest_framework.views": {"APIView": _FakeAPIView},
        }
    )
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            "baserow_infinito_sso", MODULE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


def _fake_user(**overrides):
    attributes = {
        "is_active": True,
        "email": IDENTITY["email"],
        "first_name": IDENTITY["name"],
        "is_staff": False,
        "is_superuser": False,
        "default_workspace": None,
    }
    attributes.update(overrides)
    return SimpleNamespace(
        save=MagicMock(name="save"),
        set_unusable_password=MagicMock(name="set_unusable_password"),
        **attributes,
    )


def _subject_lookup(mod):
    return mod.SsoSubject.objects.select_for_update.return_value.select_related.return_value.filter


def _wire_orm(mod, *, existing, email_taken=False, workspace_user="already-owned"):
    _subject_lookup(mod).return_value.first.return_value = (
        None if existing is None else SimpleNamespace(user=existing)
    )
    mod.User.objects.filter.return_value.exists.return_value = email_taken
    mod.UserHandler.return_value.force_create_user.return_value = _fake_user()
    mod.UserProfile.objects.get_or_create.return_value = (
        SimpleNamespace(
            email_verified=True,
            completed_onboarding=True,
            completed_guided_tours=[],
            save=MagicMock(name="profile_save"),
        ),
        False,
    )
    owned = mod.WorkspaceUser.objects.select_related.return_value.filter.return_value
    owned.order_by.return_value.first.return_value = (
        None
        if workspace_user is None
        else SimpleNamespace(workspace=workspace_user, user=existing)
    )
    mod.WorkspaceUser.objects.create.return_value = SimpleNamespace(
        workspace=mod.Workspace.objects.create.return_value
    )


class TestSsoEnabled(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def test_sso_is_disabled_when_the_environment_variable_is_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(self.mod._sso_enabled())

    def test_sso_is_enabled_for_every_documented_truthy_value(self):
        for value in ("true", "TRUE", "1", "yes", "On"):
            with patch.dict(os.environ, {"PROXY_HEADER_SSO": value}, clear=True):
                self.assertTrue(self.mod._sso_enabled(), value)

    def test_sso_stays_disabled_for_an_unrecognised_value(self):
        with patch.dict(os.environ, {"PROXY_HEADER_SSO": "maybe"}, clear=True):
            self.assertFalse(self.mod._sso_enabled())


class TestFirstHeader(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def test_returns_the_first_populated_candidate(self):
        meta = {"HTTP_A": "alice", "HTTP_B": "bob"}
        self.assertEqual(self.mod._first_header(meta, ("HTTP_A", "HTTP_B")), "alice")

    def test_skips_blank_and_whitespace_only_values(self):
        meta = {"HTTP_A": "   ", "HTTP_B": "  bob  "}
        self.assertEqual(self.mod._first_header(meta, ("HTTP_A", "HTTP_B")), "bob")

    def test_reads_the_username_from_the_preferred_username_header_only(self):
        self.assertEqual(
            self.mod.USERNAME_HEADERS, ("HTTP_X_FORWARDED_PREFERRED_USERNAME",)
        )
        self.assertIsNone(
            self.mod._first_header(
                {"HTTP_X_FORWARDED_USER": "alice@example.com"},
                self.mod.USERNAME_HEADERS,
            ),
            "oauth2-proxy fills X-Forwarded-User from the email claim "
            "(userIDClaim: email), so reading it would key the account on an address",
        )

    def test_returns_none_when_no_candidate_is_present(self):
        self.assertIsNone(self.mod._first_header({}, self.mod.USERNAME_HEADERS))

    def test_ignores_proxy_uncontrolled_identity_headers(self):
        meta = {
            "HTTP_X_AUTH_REQUEST_USER": "attacker",
            "HTTP_X_AUTH_REQUEST_PREFERRED_USERNAME": "attacker",
            "HTTP_X_AUTH_REQUEST_EMAIL": "attacker@example.com",
            "HTTP_REMOTE_USER": "attacker",
            "HTTP_X_AUTH_REQUEST_NAME": "attacker",
        }
        self.assertIsNone(self.mod._first_header(meta, self.mod.USERNAME_HEADERS))
        self.assertIsNone(self.mod._first_header(meta, self.mod.EMAIL_HEADERS))
        self.assertIsNone(self.mod._first_header(meta, self.mod.NAME_HEADERS))
        self.assertIsNone(self.mod._first_header(meta, self.mod.LOCALE_HEADERS))


class TestFallbackDomain(unittest.TestCase):
    def test_prefers_the_configured_fallback_domain(self):
        mod = _load_module()
        with patch.dict(
            os.environ,
            {"PROXY_HEADER_SSO_FALLBACK_EMAIL_DOMAIN": "mail.example.org"},
            clear=True,
        ):
            self.assertEqual(mod._fallback_domain(), "mail.example.org")

    def test_falls_back_to_the_public_frontend_hostname(self):
        mod = _load_module()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mod._fallback_domain(), HOSTNAME)

    def test_strips_scheme_and_path_from_a_url_shaped_hostname(self):
        mod = _load_module(hostname=f"https://baserow.{DOMAIN}/app")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mod._fallback_domain(), HOSTNAME)

    def test_defaults_to_localhost_when_nothing_is_configured(self):
        mod = _load_module(hostname="")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mod._fallback_domain(), "localhost")


class TestEmailFromIdentity(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def test_uses_the_forwarded_email_when_present(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                self.mod._email_from_identity("alice", " Alice@Example.COM "),
                "alice@example.com",
            )

    def test_uses_the_username_when_it_is_already_an_address(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                self.mod._email_from_identity("Alice@Example.COM", None),
                "alice@example.com",
            )

    def test_synthesises_an_address_from_the_username_and_fallback_domain(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                self.mod._email_from_identity("alice.smith", None),
                f"alice.smith@{HOSTNAME}",
            )

    def test_replaces_unsafe_characters_in_the_synthesised_local_part(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                self.mod._email_from_identity("alice smith!", None),
                f"alice.smith@{HOSTNAME}",
            )

    def test_falls_back_to_sso_user_without_any_identity(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                self.mod._email_from_identity(None, None), f"sso-user@{HOSTNAME}"
            )

    def test_falls_back_to_sso_user_when_the_local_part_collapses(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                self.mod._email_from_identity("!!!", None), f"sso-user@{HOSTNAME}"
            )


class TestDisplayName(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def test_prefers_the_forwarded_display_name(self):
        self.assertEqual(
            self.mod._display_name("alice", "alice@example.com", "Alice Smith"),
            "Alice Smith",
        )

    def test_keeps_dots_in_a_forwarded_name(self):
        self.assertEqual(
            self.mod._display_name("alice", "alice@example.com", " Dr.  Alice_Smith "),
            "Dr. Alice_Smith",
        )

    def test_turns_dots_and_underscores_into_spaces(self):
        self.assertEqual(
            self.mod._display_name("alice_the.great", "alice@example.com", None),
            "alice the great",
        )

    def test_derives_the_name_from_the_email_local_part_without_a_username(self):
        self.assertEqual(
            self.mod._display_name(None, "alice@example.com", None), "alice"
        )

    def test_uses_the_email_when_the_derived_name_is_too_short(self):
        self.assertEqual(
            self.mod._display_name("a", "alice@example.com", None), "alice@example.com"
        )

    def test_truncates_the_name_to_150_characters(self):
        self.assertEqual(
            len(self.mod._display_name("x" * 400, "alice@example.com", None)), 150
        )


class TestGroupParsing(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def test_splits_groups_on_commas_and_whitespace(self):
        self.assertEqual(
            self.mod._split_groups("/admins, users editors"),
            ["/admins", "users", "editors"],
        )

    def test_returns_no_groups_for_a_missing_header(self):
        self.assertEqual(self.mod._split_groups(None), [])

    def test_matches_the_admin_group_regardless_of_a_leading_slash(self):
        self.assertTrue(self.mod._group_matches("admins", "/admins"))
        self.assertTrue(self.mod._group_matches("/admins", "admins"))
        self.assertFalse(self.mod._group_matches("users", "/admins"))

    def test_is_admin_when_the_configured_group_is_forwarded(self):
        with patch.dict(
            os.environ, {"PROXY_HEADER_SSO_ADMIN_GROUP": "/admins"}, clear=True
        ):
            self.assertTrue(self.mod._is_admin(["users", "admins"]))

    def test_is_not_admin_when_no_admin_group_is_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(self.mod._is_admin(["admins"]))

    def test_is_not_admin_when_the_group_is_absent(self):
        with patch.dict(
            os.environ, {"PROXY_HEADER_SSO_ADMIN_GROUP": "/admins"}, clear=True
        ):
            self.assertFalse(self.mod._is_admin(["users"]))


class TestIdentityFromRequest(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def _identity(self, meta, env=SSO_ON):
        with patch.dict(os.environ, env, clear=True):
            return self.mod._identity_from_request(SimpleNamespace(META=meta))

    def test_raises_http404_when_sso_is_disabled(self):
        with self.assertRaises(_Http404Error):
            self._identity({"HTTP_X_FORWARDED_PREFERRED_USERNAME": "alice"}, env={})

    def test_raises_permission_denied_without_any_identity_header(self):
        with self.assertRaises(_PermissionDeniedError):
            self._identity({})

    def test_raises_permission_denied_without_the_preferred_username(self):
        for meta in (
            {"HTTP_X_FORWARDED_EMAIL": "alice@example.com"},
            {"HTTP_X_FORWARDED_USER": "alice@example.com"},
        ):
            with self.subTest(meta=meta), self.assertRaises(_PermissionDeniedError):
                self._identity(meta)

    def test_raises_permission_denied_for_proxy_uncontrolled_headers_only(self):
        with self.assertRaises(_PermissionDeniedError):
            self._identity(
                {
                    "HTTP_X_AUTH_REQUEST_USER": "attacker",
                    "HTTP_REMOTE_USER": "attacker",
                }
            )

    def test_builds_the_identity_from_the_forwarded_headers(self):
        identity = self._identity(
            {
                "HTTP_X_FORWARDED_PREFERRED_USERNAME": "alice.smith",
                "HTTP_X_FORWARDED_EMAIL": "Alice@Example.COM",
                "HTTP_X_FORWARDED_GROUPS": "users",
            }
        )
        self.assertEqual(
            identity,
            {
                "username": "alice.smith",
                "email": "alice@example.com",
                "name": "alice smith",
                "is_admin": False,
                "language": None,
            },
        )

    def test_reads_the_forwarded_name_and_a_supported_locale(self):
        self.mod.settings.LANGUAGES = [("en", "English"), ("de", "Deutsch")]
        identity = self._identity(
            {
                "HTTP_X_FORWARDED_PREFERRED_USERNAME": "biber",
                "HTTP_X_FORWARDED_NAME": "Harry Beaver",
                "HTTP_X_FORWARDED_LOCALE": "de-DE",
            }
        )
        self.assertEqual(
            (identity["name"], identity["language"]), ("Harry Beaver", "de")
        )

    def test_drops_an_unsupported_locale(self):
        self.mod.settings.LANGUAGES = [("en", "English")]
        identity = self._identity(
            {
                "HTTP_X_FORWARDED_PREFERRED_USERNAME": "biber",
                "HTTP_X_FORWARDED_LOCALE": "xx",
            }
        )
        self.assertIsNone(identity["language"])

    def test_synthesises_the_email_when_only_a_username_is_forwarded(self):
        identity = self._identity({"HTTP_X_FORWARDED_PREFERRED_USERNAME": "alice"})
        self.assertEqual(identity["email"], f"alice@{HOSTNAME}")

    def test_marks_the_user_as_admin_when_the_admin_group_is_forwarded(self):
        identity = self._identity(
            {
                "HTTP_X_FORWARDED_PREFERRED_USERNAME": "alice",
                "HTTP_X_FORWARDED_GROUPS": "users,/admins",
            },
            env={**SSO_ON, "PROXY_HEADER_SSO_ADMIN_GROUP": "admins"},
        )
        self.assertTrue(identity["is_admin"])


class TestGetOrCreateUser(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        env = patch.dict(os.environ, SSO_ON, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_creates_a_local_user_when_no_account_matches(self):
        _wire_orm(self.mod, existing=None)
        user = self.mod._get_or_create_user(dict(IDENTITY))
        self.mod.UserHandler.return_value.force_create_user.assert_called_once_with(
            email=IDENTITY["email"],
            name=IDENTITY["name"],
            password=None,
            is_staff=False,
            is_superuser=False,
        )
        user.set_unusable_password.assert_called_once_with()
        user.save.assert_any_call(update_fields=["password"])
        self.mod.SsoSubject.objects.create.assert_called_once_with(
            user=user, username=IDENTITY["username"]
        )

    def test_creates_the_user_as_staff_and_superuser_for_an_admin_identity(self):
        _wire_orm(self.mod, existing=None)
        self.mod._get_or_create_user({**IDENTITY, "is_admin": True})
        kwargs = self.mod.UserHandler.return_value.force_create_user.call_args.kwargs
        self.assertTrue(kwargs["is_staff"])
        self.assertTrue(kwargs["is_superuser"])

    def test_reuses_the_existing_account_instead_of_creating_one(self):
        existing = _fake_user()
        _wire_orm(self.mod, existing=existing)
        self.assertIs(self.mod._get_or_create_user(dict(IDENTITY)), existing)
        self.mod.UserHandler.return_value.force_create_user.assert_not_called()
        self.mod.SsoSubject.objects.create.assert_not_called()
        existing.save.assert_not_called()

    def test_resolves_the_account_by_its_sso_subject_never_by_email(self):
        _wire_orm(self.mod, existing=_fake_user())
        self.mod._get_or_create_user(dict(IDENTITY))
        _subject_lookup(self.mod).assert_called_once_with(username=IDENTITY["username"])
        self.mod.User.objects.filter.assert_not_called()

    def test_refuses_an_unbound_login_whose_email_belongs_to_an_account(self):
        _wire_orm(self.mod, existing=None, email_taken=True)
        with self.assertRaises(_PermissionDeniedError):
            self.mod._get_or_create_user(dict(IDENTITY))
        self.assertEqual(
            self.mod.User.objects.filter.call_args.args[0].terms,
            [
                {"email__iexact": IDENTITY["email"]},
                {"username__iexact": IDENTITY["email"]},
            ],
        )
        self.mod.UserHandler.return_value.force_create_user.assert_not_called()
        self.mod.SsoSubject.objects.create.assert_not_called()

    def test_repairs_an_inactive_or_incomplete_existing_account(self):
        existing = _fake_user(is_active=False, email="", first_name="A")
        _wire_orm(self.mod, existing=existing)
        self.mod._get_or_create_user(dict(IDENTITY))
        self.assertTrue(existing.is_active)
        self.assertEqual(existing.email, IDENTITY["email"])
        self.assertEqual(existing.first_name, IDENTITY["name"])
        existing.save.assert_called_once_with(
            update_fields=["is_active", "email", "first_name"]
        )

    def test_promotes_an_existing_account_for_an_admin_identity(self):
        existing = _fake_user()
        _wire_orm(self.mod, existing=existing)
        self.mod._get_or_create_user({**IDENTITY, "is_admin": True})
        self.assertTrue(existing.is_staff)
        self.assertTrue(existing.is_superuser)
        existing.save.assert_called_once_with(
            update_fields=["is_staff", "is_superuser"]
        )

    def test_demotes_an_existing_admin_outside_the_admin_group(self):
        existing = _fake_user(is_staff=True, is_superuser=True)
        _wire_orm(self.mod, existing=existing)
        self.mod._get_or_create_user(dict(IDENTITY))
        self.assertFalse(existing.is_staff)
        self.assertFalse(existing.is_superuser)
        existing.save.assert_called_once_with(
            update_fields=["is_staff", "is_superuser"]
        )

    def test_never_demotes_the_bootstrap_admin(self):
        existing = _fake_user(
            email=BOOTSTRAP_EMAIL.upper(), is_staff=True, is_superuser=True
        )
        _wire_orm(self.mod, existing=existing)
        self.mod._get_or_create_user({**IDENTITY, "email": BOOTSTRAP_EMAIL})
        self.assertTrue(existing.is_staff)
        self.assertTrue(existing.is_superuser)
        existing.save.assert_not_called()

    def test_overwrites_a_stale_first_name_with_the_identity_name(self):
        existing = _fake_user(first_name="Ally")
        _wire_orm(self.mod, existing=existing)
        self.mod._get_or_create_user(dict(IDENTITY))
        self.assertEqual(existing.first_name, IDENTITY["name"])
        existing.save.assert_called_once_with(update_fields=["first_name"])

    def test_keeps_a_current_first_name_without_saving(self):
        existing = _fake_user()
        _wire_orm(self.mod, existing=existing)
        self.mod._get_or_create_user(dict(IDENTITY))
        existing.save.assert_not_called()


class TestEnsureProfile(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def _profile(self, **overrides):
        attributes = {
            "email_verified": True,
            "completed_onboarding": True,
            "completed_guided_tours": [],
        }
        attributes.update(overrides)
        profile = SimpleNamespace(save=MagicMock(name="profile_save"), **attributes)
        self.mod.UserProfile.objects.get_or_create.return_value = (profile, False)
        return profile

    def test_creates_the_profile_with_the_configured_language(self):
        self._profile()
        user = _fake_user()
        self.mod._ensure_profile(user, None)
        self.mod.UserProfile.objects.get_or_create.assert_called_once_with(
            user=user, defaults={"language": "en"}
        )

    def test_creates_the_profile_with_the_forwarded_language(self):
        self._profile(language="de")
        user = _fake_user()
        self.mod._ensure_profile(user, "de")
        self.mod.UserProfile.objects.get_or_create.assert_called_once_with(
            user=user, defaults={"language": "de"}
        )

    def test_updates_the_language_of_an_existing_profile(self):
        profile = self._profile(language="en")
        self.mod._ensure_profile(_fake_user(), "de")
        self.assertEqual(profile.language, "de")
        profile.save.assert_called_once_with(update_fields=["language"])

    def test_leaves_a_complete_profile_untouched(self):
        profile = self._profile()
        self.mod._ensure_profile(_fake_user(), None)
        profile.save.assert_not_called()

    def test_repairs_an_unverified_and_unonboarded_profile(self):
        profile = self._profile(
            email_verified=False,
            completed_onboarding=False,
            completed_guided_tours=None,
        )
        self.mod._ensure_profile(_fake_user(), None)
        self.assertTrue(profile.email_verified)
        self.assertTrue(profile.completed_onboarding)
        self.assertEqual(profile.completed_guided_tours, [])
        profile.save.assert_called_once_with(
            update_fields=[
                "email_verified",
                "completed_onboarding",
                "completed_guided_tours",
            ]
        )


class TestEnsureWorkspace(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def test_creates_a_named_admin_workspace_when_the_user_has_none(self):
        _wire_orm(self.mod, existing=None, workspace_user=None)
        user = _fake_user()
        self.mod._ensure_workspace(user, "Alice Smith")
        self.mod.Workspace.objects.create.assert_called_once_with(
            name="Alice Smith's workspace"
        )
        self.assertEqual(
            self.mod.WorkspaceUser.objects.create.call_args.kwargs["permissions"],
            "ADMIN",
        )
        self.assertIs(
            user.default_workspace, self.mod.Workspace.objects.create.return_value
        )

    def test_reuses_the_first_workspace_the_user_already_belongs_to(self):
        _wire_orm(self.mod, existing=None, workspace_user="already-owned")
        user = _fake_user()
        self.mod._ensure_workspace(user, "Alice Smith")
        self.mod.Workspace.objects.create.assert_not_called()
        self.mod.WorkspaceUser.objects.create.assert_not_called()
        self.assertEqual(user.default_workspace, "already-owned")


class TestSafeNextUrl(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def _safe(self, next_url):
        query = {} if next_url is None else {"next": next_url}
        return self.mod._safe_next_url(SimpleNamespace(GET=query))

    def test_keeps_a_relative_path_with_its_query(self):
        self.assertEqual(self._safe("/database/42?view=grid"), "/database/42?view=grid")

    def test_defaults_to_the_root_when_next_is_missing(self):
        self.assertEqual(self._safe(None), "/")

    def test_rejects_an_absolute_url(self):
        self.assertEqual(self._safe("https://evil.example/steal"), "/")

    def test_rejects_a_protocol_relative_url(self):
        self.assertEqual(self._safe("//evil.example/steal"), "/")

    def test_rejects_a_backslash_disguised_absolute_url(self):
        self.assertEqual(self._safe("\\\\evil.example/steal"), "/")

    def test_rejects_a_path_that_does_not_start_at_the_root(self):
        self.assertEqual(self._safe("dashboard"), "/")

    def test_rejects_a_protocol_relative_url_smuggled_behind_whitespace(self):
        self.assertEqual(self._safe("/\t/evil.example/steal"), "/")
        self.assertEqual(self._safe("/\r\n//evil.example/steal"), "/evil.example/steal")


class TestViews(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        self.payload = {"refresh_token": "refresh-1", "user_session": "session-1"}

    def _redirect_target(self, next_url):
        request = SimpleNamespace(GET={"next": next_url})
        with patch.object(self.mod, "_login_payload", return_value=self.payload):
            self.mod.ProxyHeaderLoginView().get(request)
        return self.mod.redirect.call_args.args[0]

    def test_the_token_view_returns_the_login_payload(self):
        request = SimpleNamespace(GET={})
        with patch.object(self.mod, "_login_payload", return_value=self.payload):
            self.assertEqual(
                self.mod.ProxyHeaderTokenView().get(request).data, self.payload
            )
            self.assertEqual(
                self.mod.ProxyHeaderTokenView().post(request).data, self.payload
            )

    def test_the_login_view_appends_the_tokens_to_the_next_url(self):
        self.assertEqual(
            self._redirect_target("/dashboard"),
            "/dashboard?token=refresh-1&user_session=session-1",
        )

    def test_the_login_view_joins_an_existing_query_with_an_ampersand(self):
        self.assertEqual(
            self._redirect_target("/database/42?view=grid"),
            "/database/42?view=grid&token=refresh-1&user_session=session-1",
        )

    def test_the_login_view_redirects_an_unsafe_next_url_to_the_root(self):
        self.assertEqual(
            self._redirect_target("https://evil.example"),
            "/?token=refresh-1&user_session=session-1",
        )

    def test_the_login_payload_provisions_the_user_from_the_request_identity(self):
        request = SimpleNamespace(META={"HTTP_X_FORWARDED_PREFERRED_USERNAME": "alice"})
        _wire_orm(self.mod, existing=_fake_user())
        with patch.dict(os.environ, SSO_ON, clear=True):
            payload = self.mod._login_payload(request)
        self.assertIs(payload, self.mod.log_in_user.return_value)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/web-app-bookwyrm/files/sso/header_auth.py"
DOMAIN_PRIMARY = default_domain_primary()
DOMAIN = f"book.{DOMAIN_PRIMARY}"


class _FakeMiddlewareBase:
    def __init__(self, get_response=None):
        self.get_response = get_response

    def process_request(self, request):
        return None


class _FakeRemoteUserBackend:
    create_unknown_user = True

    def clean_username(self, username):
        return username

    def user_can_authenticate(self, user):
        return getattr(user, "is_active", True)


def _fake_user_model(*, existing):
    does_not_exist = type("DoesNotExist", (Exception,), {})
    objects = MagicMock(name="objects")
    if existing is None:
        objects.get.side_effect = does_not_exist
        objects.create_user.return_value = MagicMock(
            name="created_user", is_active=True
        )
    else:
        objects.get.return_value = existing
    model = MagicMock(name="User")
    model.DoesNotExist = does_not_exist
    model.objects = objects
    return model


def _load_module(user_model):
    """Import header_auth.py with Django stubbed out (no Django dependency)."""
    conf = ModuleType("django.conf")
    conf.settings = SimpleNamespace(DOMAIN=DOMAIN, LANGUAGES=[("en-us", "English")])
    backends = ModuleType("django.contrib.auth.backends")
    backends.RemoteUserBackend = _FakeRemoteUserBackend
    middleware = ModuleType("django.contrib.auth.middleware")
    middleware.PersistentRemoteUserMiddleware = _FakeMiddlewareBase
    auth = ModuleType("django.contrib.auth")
    auth.get_user_model = MagicMock(return_value=user_model)
    contrib = ModuleType("django.contrib")
    contrib.auth = auth
    django = ModuleType("django")
    django.contrib = contrib
    django.conf = conf

    stubs = {
        "django": django,
        "django.conf": conf,
        "django.contrib": contrib,
        "django.contrib.auth": auth,
        "django.contrib.auth.backends": backends,
        "django.contrib.auth.middleware": middleware,
    }
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            "bookwyrm_header_auth", MODULE_PATH
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


class TestFirstHeader(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module(_fake_user_model(existing=None))

    def test_returns_first_present_candidate(self):
        meta = {"HTTP_X_FORWARDED_EMAIL": "alice@example.org"}
        self.assertEqual(
            self.mod._first_header(meta, self.mod.CANDIDATE_EMAIL_HEADERS),
            "alice@example.org",
        )

    def test_returns_none_when_absent(self):
        self.assertIsNone(self.mod._first_header({}, self.mod.CANDIDATE_EMAIL_HEADERS))


class TestProxyHeaderMiddleware(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module(_fake_user_model(existing=None))
        self.mw = self.mod.ProxyHeaderMiddleware(lambda request: request)

    def test_the_identity_header_is_the_preferred_username(self):
        self.assertEqual(
            self.mod.CANONICAL_HEADER, "HTTP_X_FORWARDED_PREFERRED_USERNAME"
        )

    def test_forwarded_user_never_becomes_the_identity(self):
        request = SimpleNamespace(
            META={"HTTP_X_FORWARDED_USER": "administrator@attacker.example"}
        )
        self.mw.process_request(request)
        self.assertNotIn(self.mod.CANONICAL_HEADER, request.META)

    def test_proxy_uncontrolled_headers_never_become_the_identity(self):
        request = SimpleNamespace(
            META={
                "HTTP_X_AUTH_REQUEST_USER": "attacker",
                "HTTP_X_AUTH_REQUEST_PREFERRED_USERNAME": "attacker",
                "HTTP_REMOTE_USER": "attacker",
            }
        )
        self.mw.process_request(request)
        self.assertNotIn(self.mod.CANONICAL_HEADER, request.META)

    def test_keeps_existing_canonical_header(self):
        request = SimpleNamespace(
            META={self.mod.CANONICAL_HEADER: "bob", "HTTP_X_FORWARDED_USER": "alice"}
        )
        self.mw.process_request(request)
        self.assertEqual(request.META[self.mod.CANONICAL_HEADER], "bob")

    def test_no_candidate_leaves_request_anonymous(self):
        request = SimpleNamespace(META={})
        self.mw.process_request(request)
        self.assertNotIn(self.mod.CANONICAL_HEADER, request.META)


class TestProxyHeaderBackend(unittest.TestCase):
    def test_empty_remote_user_returns_none(self):
        mod = _load_module(_fake_user_model(existing=None))
        self.assertIsNone(
            mod.ProxyHeaderBackend().authenticate(SimpleNamespace(META={}), "")
        )

    def test_existing_local_user_is_returned(self):
        existing = MagicMock(name="existing", is_active=True)
        model = _fake_user_model(existing=existing)
        backend = _load_module(model).ProxyHeaderBackend()
        user = backend.authenticate(SimpleNamespace(META={}), "administrator")
        self.assertIs(user, existing)
        model.objects.get.assert_called_once_with(
            localname__iexact="administrator", local=True
        )
        model.objects.create_user.assert_not_called()

    def test_unknown_user_is_provisioned_local(self):
        model = _fake_user_model(existing=None)
        backend = _load_module(model).ProxyHeaderBackend()
        user = backend.authenticate(SimpleNamespace(META={}), "administrator")
        model.objects.create_user.assert_called_once()
        args, kwargs = model.objects.create_user.call_args
        self.assertEqual(args[0], f"administrator@{DOMAIN}")
        self.assertEqual(kwargs["localname"], "administrator")
        self.assertTrue(kwargs["local"])
        self.assertTrue(kwargs["is_active"])
        self.assertIs(user, model.objects.create_user.return_value)

    def test_unknown_user_not_created_when_disabled(self):
        model = _fake_user_model(existing=None)
        backend = _load_module(model).ProxyHeaderBackend()
        backend.create_unknown_user = False
        self.assertIsNone(
            backend.authenticate(SimpleNamespace(META={}), "administrator")
        )
        model.objects.create_user.assert_not_called()


GROUP_MAP = {
    "/roles/web-app-bookwyrm/administrator": "admin",
    "/roles/web-app-bookwyrm/moderator": "moderator",
    "/roles/web-app-bookwyrm/editor": "editor",
    "/roles/web-app-bookwyrm/owner": "owner",
}


def _filter_groups_by_name(name__in):
    return sorted(name__in)


class _FakeGroups:
    def __init__(self, names):
        self.names = set(names)
        self.model = SimpleNamespace(
            objects=SimpleNamespace(filter=_filter_groups_by_name)
        )

    def values_list(self, field, flat):
        return sorted(self.names)

    def set(self, groups):
        self.names = set(groups)


def _identity(groups=(), name=None, language=None, timezone=None):
    return {
        "groups": list(groups),
        "name": name,
        "language": language,
        "timezone": timezone,
    }


def _fake_user(groups=(), **fields):
    user = SimpleNamespace(
        groups=_FakeGroups(groups),
        is_superuser=False,
        is_staff=False,
        is_authenticated=True,
        local=True,
        localname="biber",
        name="biber",
        preferred_language="en-us",
        preferred_timezone="UTC",
        saves=0,
    )
    for key, value in fields.items():
        setattr(user, key, value)

    def save(broadcast):
        user.saves += 1
        user.broadcast = broadcast

    user.save = save
    return user


class TestIdentityMapping(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module(_fake_user_model(existing=None))

    def test_desired_groups_maps_only_declared_paths(self):
        header = "/roles/web-app-bookwyrm/moderator,/roles/web-app-other/administrator"
        self.assertEqual(self.mod.desired_groups(header, GROUP_MAP), {"moderator"})

    def test_identity_reads_the_groups_header(self):
        request = SimpleNamespace(
            META={self.mod.GROUPS_HEADER: "/roles/web-app-bookwyrm/editor"}
        )
        self.assertEqual(
            self.mod.identity_from_request(request, GROUP_MAP),
            _identity(groups=["editor"]),
        )

    def test_identity_reads_name_locale_and_zoneinfo(self):
        self.mod.settings.LANGUAGES = [("en-us", "English"), ("de-de", "Deutsch")]
        request = SimpleNamespace(
            META={
                self.mod.NAME_HEADER: " Harry Beaver ",
                self.mod.LOCALE_HEADER: "de",
                self.mod.ZONEINFO_HEADER: "Europe/Berlin",
            }
        )
        self.assertEqual(
            self.mod.identity_from_request(request, GROUP_MAP),
            _identity(name="Harry Beaver", language="de-de", timezone="Europe/Berlin"),
        )

    def test_language_prefers_an_exact_code(self):
        self.mod.settings.LANGUAGES = [
            ("pt-pt", "Português"),
            ("pt-br", "Português do Brasil"),
        ]
        self.assertEqual(self.mod.language_for("pt_BR"), "pt-br")
        self.assertEqual(self.mod.language_for("pt"), "pt-pt")

    def test_unknown_language_and_zone_are_dropped(self):
        self.mod.settings.LANGUAGES = [("en-us", "English")]
        self.assertIsNone(self.mod.language_for("xx"))
        self.assertIsNone(self.mod.language_for(""))
        self.assertIsNone(self.mod.timezone_for("Mars/Olympus"))
        self.assertIsNone(self.mod.timezone_for("../etc/passwd"))

    def test_apply_writes_the_forwarded_profile(self):
        user = _fake_user()
        changed = self.mod.apply_identity(
            user,
            _identity(name="Harry Beaver", language="de-de", timezone="Europe/Berlin"),
            GROUP_MAP,
        )
        self.assertTrue(changed)
        self.assertEqual(
            (user.name, user.preferred_language, user.preferred_timezone),
            ("Harry Beaver", "de-de", "Europe/Berlin"),
        )
        self.assertEqual(user.saves, 1)
        self.assertTrue(
            user.broadcast, "a changed display name must reach the followers"
        )

    def test_a_staff_change_alone_is_not_broadcast(self):
        user = _fake_user()
        self.mod.apply_identity(user, _identity(groups=["admin"]), GROUP_MAP)
        self.assertEqual(user.saves, 1)
        self.assertFalse(user.broadcast)

    def test_absent_profile_fields_keep_the_stored_values(self):
        user = _fake_user()
        self.mod.apply_identity(user, _identity(), GROUP_MAP)
        self.assertEqual(
            (user.name, user.preferred_language, user.preferred_timezone),
            ("biber", "en-us", "UTC"),
        )
        self.assertEqual(user.saves, 0)

    def test_apply_promotes_and_keeps_unmanaged_groups(self):
        user = _fake_user(groups=["readers"])
        changed = self.mod.apply_identity(user, _identity(groups=["admin"]), GROUP_MAP)
        self.assertTrue(changed)
        self.assertEqual(user.groups.names, {"admin", "readers"})
        self.assertTrue(user.is_staff)
        self.assertEqual(user.saves, 1)

    def test_apply_demotes_managed_groups(self):
        user = _fake_user(groups=["moderator", "readers"], is_staff=True)
        self.mod.apply_identity(user, _identity(), GROUP_MAP)
        self.assertEqual(user.groups.names, {"readers"})
        self.assertFalse(user.is_staff)

    def test_apply_leaves_superuser_staff_flag(self):
        user = _fake_user(is_superuser=True, is_staff=True)
        self.mod.apply_identity(user, _identity(), GROUP_MAP)
        self.assertTrue(user.is_staff)
        self.assertEqual(user.saves, 0)


class TestSyncIdentity(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module(_fake_user_model(existing=None))
        self.env = patch.dict(
            os.environ,
            {
                self.mod.GROUP_MAP_ENV: json.dumps(GROUP_MAP),
                self.mod.BOOTSTRAP_ADMIN_ENV: "platformadmin",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_bootstrap_admin_is_left_alone(self):
        user = _fake_user(groups=["admin", "moderator"], localname="PlatformAdmin")
        request = SimpleNamespace(META={}, user=user, session={})
        self.mod.sync_identity(request)
        self.assertEqual(user.groups.names, {"admin", "moderator"})
        self.assertEqual(request.session, {})

    def test_unchanged_identity_is_applied_once_per_session(self):
        user = _fake_user()
        request = SimpleNamespace(
            META={self.mod.GROUPS_HEADER: "/roles/web-app-bookwyrm/owner"},
            user=user,
            session={},
        )
        self.mod.sync_identity(request)
        self.assertEqual(user.groups.names, {"owner"})
        user.groups.names = set()
        self.mod.sync_identity(request)
        self.assertEqual(user.groups.names, set())
        self.assertIn(self.mod.SESSION_KEY, request.session)


if __name__ == "__main__":
    unittest.main()

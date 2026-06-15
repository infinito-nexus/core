from __future__ import annotations

import importlib.util
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/web-app-bookwyrm/files/sso/header_auth.py"
DOMAIN = "book.infinito.example"


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
    conf.settings = SimpleNamespace(DOMAIN=DOMAIN)
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
        meta = {
            "HTTP_X_FORWARDED_PREFERRED_USERNAME": "alice",
            "HTTP_X_FORWARDED_USER": "bob",
        }
        self.assertEqual(
            self.mod._first_header(meta, self.mod.CANDIDATE_USERNAME_HEADERS), "alice"
        )

    def test_returns_none_when_absent(self):
        self.assertIsNone(
            self.mod._first_header({}, self.mod.CANDIDATE_USERNAME_HEADERS)
        )

    def test_ignores_proxy_uncontrolled_headers(self):
        meta = {
            "HTTP_X_AUTH_REQUEST_USER": "attacker",
            "HTTP_X_AUTH_REQUEST_PREFERRED_USERNAME": "attacker",
            "HTTP_REMOTE_USER": "attacker",
        }
        self.assertIsNone(
            self.mod._first_header(meta, self.mod.CANDIDATE_USERNAME_HEADERS)
        )


class TestProxyHeaderMiddleware(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module(_fake_user_model(existing=None))
        self.mw = self.mod.ProxyHeaderMiddleware(lambda request: request)

    def test_copies_candidate_into_canonical_header(self):
        request = SimpleNamespace(META={"HTTP_X_FORWARDED_USER": "alice"})
        self.mw.process_request(request)
        self.assertEqual(request.META[self.mod.CANONICAL_HEADER], "alice")

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


if __name__ == "__main__":
    unittest.main()

"""Stand-ins for the Weblate 2026.9 pieces the shipped modules subclass or read."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT, read_text

if TYPE_CHECKING:
    from pathlib import Path

PYTHON_DIR = PROJECT_ROOT / "roles/web-app-weblate/files/python"
OVERRIDE_PATH = PYTHON_DIR / "settings_override.py"
NETWORK_PACKAGE = "weblate_network"
STRATEGY_MODULE_PATH = PYTHON_DIR / NETWORK_PACKAGE / "strategy.py"
MIDDLEWARE_MODULE_PATH = PYTHON_DIR / NETWORK_PACKAGE / "middleware.py"
STRATEGY_MODULE = f"{NETWORK_PACKAGE}.strategy"
MIDDLEWARE_MODULE = f"{NETWORK_PACKAGE}.middleware"
CLEARNET = "web.translate.example.com"
ONION = "web.translate." + "a" * 56 + ".onion"
SITE_URL = f"https://{CLEARNET}"
ALLOWED_HOSTS = (CLEARNET, ONION, "weblate")
CALLBACK = "/accounts/complete/oidc/"
UPSTREAM_PROXY = "weblate.middleware.ProxyMiddleware"
UPSTREAM_STRATEGY = "weblate.accounts.strategy.WeblateStrategy"
UPSTREAM_APPS = ["customize", "weblate.addons", "weblate.auth", "weblate.checks"]
UPSTREAM_MIDDLEWARE = [
    "weblate.middleware.RedirectMiddleware",
    UPSTREAM_PROXY,
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "weblate.accounts.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "social_django.middleware.SocialAuthExceptionMiddleware",
    "weblate.api.middleware.ThrottlingMiddleware",
    "weblate.middleware.SecurityMiddleware",
    "weblate.wladmin.middleware.ManageMiddleware",
]
ASSOCIATE_BY_EMAIL = "social_core.pipeline.social_auth.associate_by_email"
UPSTREAM_PIPELINE_SOURCE = "https://github.com/WeblateOrg/weblate/blob/weblate-2026.9/weblate/settings_docker.py#L639-L664"
UPSTREAM_PIPELINE = [
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "weblate.accounts.pipeline.store_params",
    "weblate.accounts.pipeline.verify_open",
    "social_core.pipeline.user.get_username",
    "weblate.accounts.pipeline.require_email",
    "social_core.pipeline.mail.mail_validation",
    "weblate.accounts.pipeline.revoke_mail_code",
    "weblate.accounts.pipeline.ensure_valid",
    "weblate.accounts.pipeline.remove_account",
    ASSOCIATE_BY_EMAIL,
    "weblate.accounts.pipeline.reauthenticate",
    "weblate.accounts.pipeline.verify_username",
    "social_core.pipeline.user.create_user",
    "social_core.pipeline.social_auth.associate_user",
    "weblate.accounts.pipeline.handle_invite",
    "social_core.pipeline.social_auth.load_extra_data",
    "weblate.accounts.pipeline.second_factor",
    "weblate.accounts.pipeline.user_full_name",
    "weblate.accounts.pipeline.store_email",
    "weblate.accounts.pipeline.notify_connect",
    "weblate.accounts.pipeline.password_reset",
]


class DisallowedHostError(Exception):
    pass


class FakeRequest:
    """The parts of Django's ``HttpRequest`` Weblate's origin code touches.

    Args:
        host: the ``Host`` header, optionally with a port.
        secure: whether ``SECURE_PROXY_SSL_HEADER`` marked the request secure.
        meta: extra ``META`` entries.
    """

    def __init__(self, host: str, *, secure: bool, meta: dict | None = None):
        self._host = host
        self._secure = secure
        self.META = {"REMOTE_ADDR": "10.0.0.2", **(meta or {})}

    @property
    def scheme(self) -> str:
        return "https" if self._secure else "http"

    def is_secure(self) -> bool:
        return self._secure

    def get_host(self) -> str:
        if self._host.split(":", 1)[0] not in ALLOWED_HOSTS:
            raise DisallowedHostError(self._host)
        return self._host

    def build_absolute_uri(self, path: str | None = None) -> str:
        if "_current_scheme_host" not in self.__dict__:
            self.__dict__["_current_scheme_host"] = f"{self.scheme}://{self.get_host()}"
        return f"{self.__dict__['_current_scheme_host']}{path or '/'}"


class UpstreamProxyMiddleware:
    """weblate.middleware.ProxyMiddleware as of weblate-2026.9."""

    def __init__(self, get_response=None):
        self.get_response = get_response

    def process_request(self, request):
        request.__dict__["_current_scheme_host"] = SITE_URL
        proxy = request.META.get("HTTP_X_FORWARDED_FOR")
        if proxy:
            request.META["REMOTE_ADDR"] = proxy.split(",")[0].strip()


class UpstreamStrategy:
    """weblate.accounts.strategy.WeblateStrategy as of weblate-2026.9."""

    def __init__(self, request=None):
        self.request = request

    def build_absolute_uri(self, path=None):
        if self.request:
            self.request.__dict__["_current_scheme_host"] = SITE_URL
            return self.request.build_absolute_uri(path)
        return path

    def request_is_secure(self):
        return True

    def request_host(self):
        return CLEARNET

    def request_port(self):
        return None


def upstream_settings() -> dict:
    """Return the settings_docker.py values of weblate-2026.9 the override reads or replaces."""
    return {
        "INSTALLED_APPS": list(UPSTREAM_APPS),
        "MIDDLEWARE": list(UPSTREAM_MIDDLEWARE),
        "SOCIAL_AUTH_STRATEGY": UPSTREAM_STRATEGY,
        "SOCIAL_AUTH_REDIRECT_IS_HTTPS": True,
        "SECURE_SSL_REDIRECT": True,
        "LANGUAGE_COOKIE_SAMESITE": "None",
        "SOCIAL_AUTH_PIPELINE": list(UPSTREAM_PIPELINE),
    }


def apply_override(namespace: dict, override: Path = OVERRIDE_PATH) -> dict:
    """Exec the override the way settings_docker.py does, restoring ``sys.path``.

    Args:
        namespace: the settings module namespace the override runs in.
        override: the override file to exec.

    Returns:
        The namespace after the override ran.
    """
    saved = list(sys.path)
    try:
        code = compile(read_text(str(override)), str(override), "exec")
        exec(code, namespace)
    finally:
        sys.path[:] = saved
    return namespace


def _exec_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_shipped() -> dict[str, ModuleType]:
    """Import the shipped modules against the upstream stand-ins above.

    Returns:
        ``{"strategy": <module>, "middleware": <module>}``; ``sys.modules`` is
        restored afterwards.
    """
    strategy = ModuleType("weblate.accounts.strategy")
    strategy.WeblateStrategy = UpstreamStrategy
    middleware = ModuleType("weblate.middleware")
    middleware.ProxyMiddleware = UpstreamProxyMiddleware
    package = ModuleType(NETWORK_PACKAGE)
    package.__path__ = [str(STRATEGY_MODULE_PATH.parent)]
    stubs = {
        "weblate": ModuleType("weblate"),
        "weblate.accounts": ModuleType("weblate.accounts"),
        "weblate.accounts.strategy": strategy,
        "weblate.middleware": middleware,
        NETWORK_PACKAGE: package,
    }
    names = [*stubs, STRATEGY_MODULE, MIDDLEWARE_MODULE]
    saved = {name: sys.modules.get(name) for name in names}
    sys.modules.update(stubs)
    try:
        return {
            "strategy": _exec_module(STRATEGY_MODULE, STRATEGY_MODULE_PATH),
            "middleware": _exec_module(MIDDLEWARE_MODULE, MIDDLEWARE_MODULE_PATH),
        }
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

# ruff: noqa: F821
import os as _infinito_sso_os

if _infinito_sso_os.environ.get("PROXY_HEADER_SSO", "").lower() in ("true", "1", "yes"):
    _infinito_auth_mw = "django.contrib.auth.middleware.AuthenticationMiddleware"
    _infinito_sso_mw = "bookwyrm.header_auth.ProxyHeaderMiddleware"
    if _infinito_sso_mw not in MIDDLEWARE:
        MIDDLEWARE.insert(MIDDLEWARE.index(_infinito_auth_mw) + 1, _infinito_sso_mw)
    AUTHENTICATION_BACKENDS = [
        "bookwyrm.header_auth.ProxyHeaderBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]

# ruff: noqa: F821
import os as _infinito_sso_os

if _infinito_sso_os.environ.get("PROXY_HEADER_SSO", "").lower() in (
    "true",
    "1",
    "yes",
    "on",
):
    from django.urls import include as _infinito_sso_include
    from django.urls import path as _infinito_sso_path

    urlpatterns = [
        _infinito_sso_path(
            "api/infinito/sso/",
            _infinito_sso_include("baserow.infinito_sso"),
        ),
        *urlpatterns,
    ]

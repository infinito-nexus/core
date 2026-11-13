"""Weblate settings override for serving every network sibling of its domain
and for linking SSO logins by subject only.

Weblate execs ``/app/data/settings-override.py`` at the end of its
``settings_docker.py`` inside that module's namespace, so ``MIDDLEWARE``,
``SOCIAL_AUTH_STRATEGY`` and ``SOCIAL_AUTH_PIPELINE`` are upstream's final
values here and every name bound below lands in Django's settings. With SSO
on (``WEBLATE_SOCIAL_AUTH_OIDC_KEY`` set) the pipeline loses
``associate_by_email`` and every other step keeps its upstream position.
"""

import os
import sys

_infinito_origin_dir = "/app/infinito"
_infinito_upstream_proxy = "weblate.middleware.ProxyMiddleware"
_infinito_upstream_strategy = "weblate.accounts.strategy.WeblateStrategy"
_infinito_associate_by_email = "social_core.pipeline.social_auth.associate_by_email"

if _infinito_upstream_proxy not in MIDDLEWARE:  # noqa: F821
    raise RuntimeError(
        f"{_infinito_upstream_proxy} is no longer in MIDDLEWARE; re-check "
        "weblate_network.middleware against this Weblate release"
    )
if _infinito_upstream_strategy != SOCIAL_AUTH_STRATEGY:  # noqa: F821
    raise RuntimeError(
        f"SOCIAL_AUTH_STRATEGY is no longer {_infinito_upstream_strategy}; "
        "re-check weblate_network.strategy against this Weblate release"
    )

if _infinito_origin_dir not in sys.path:
    sys.path.append(_infinito_origin_dir)

INSTALLED_APPS = [*INSTALLED_APPS, "weblate_infinito"]  # noqa: F821
MIDDLEWARE = [
    "weblate_network.middleware.NetworkProxyMiddleware"
    if entry == _infinito_upstream_proxy
    else entry
    for entry in MIDDLEWARE  # noqa: F821
]
SOCIAL_AUTH_STRATEGY = "weblate_network.strategy.NetworkStrategy"
SOCIAL_AUTH_REDIRECT_IS_HTTPS = False
SECURE_SSL_REDIRECT = False
LANGUAGE_COOKIE_SAMESITE = "Lax"
if os.environ.get("WEBLATE_SOCIAL_AUTH_OIDC_KEY"):
    SOCIAL_AUTH_PIPELINE = [
        step
        for step in SOCIAL_AUTH_PIPELINE  # noqa: F821
        if step != _infinito_associate_by_email
    ]

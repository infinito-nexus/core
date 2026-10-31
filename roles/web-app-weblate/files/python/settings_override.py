"""Weblate settings override for serving every network sibling of its domain.

Weblate execs ``/app/data/settings-override.py`` at the end of its
``settings_docker.py`` inside that module's namespace, so ``MIDDLEWARE`` and
``SOCIAL_AUTH_STRATEGY`` are upstream's final values here and every name bound
below lands in Django's settings.
"""

import sys

_infinito_origin_dir = "/app/infinito"
_infinito_upstream_proxy = "weblate.middleware.ProxyMiddleware"
_infinito_upstream_strategy = "weblate.accounts.strategy.WeblateStrategy"

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

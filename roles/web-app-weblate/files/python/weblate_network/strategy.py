"""Weblate's social-auth strategy on the network sibling a request came in on.

Upstream ``WeblateStrategy`` overwrites the request's ``_current_scheme_host``
with ``get_site_url()`` and answers ``request_is_secure``/``request_host``/
``request_port`` from settings, so every OIDC ``redirect_uri`` names the
clearnet host. The subclass takes scheme and host from the request instead.

``social_django.utils`` imports this module at app-ready time through
``module_member(SOCIAL_AUTH_STRATEGY)``, before it defines ``load_strategy``.
It must import nothing beyond what ``weblate.accounts.strategy`` already pulls
in; ``weblate.middleware`` imports ``load_strategy`` back and crash-loops the
container on a circular import.
"""

from urllib.parse import urlparse

from weblate.accounts.strategy import WeblateStrategy

SCHEME_HOST_ATTRIBUTE = "_current_scheme_host"


def request_origin(request) -> str:
    """Return the origin a request reached Weblate on.

    Args:
        request: a Django ``HttpRequest``. ``scheme`` honours
            ``SECURE_PROXY_SSL_HEADER``; ``get_host()`` raises
            ``DisallowedHost`` for a host outside ``ALLOWED_HOSTS``.

    Returns:
        ``<scheme>://<host>``, the host with its port when the request named one.
    """
    return f"{request.scheme}://{request.get_host()}"


class NetworkStrategy(WeblateStrategy):
    def build_absolute_uri(self, path=None):
        if not self.request:
            return super().build_absolute_uri(path)
        self.request.__dict__[SCHEME_HOST_ATTRIBUTE] = request_origin(self.request)
        return self.request.build_absolute_uri(path)

    def request_is_secure(self):
        if not self.request:
            return super().request_is_secure()
        return self.request.is_secure()

    def request_host(self):
        if not self.request:
            return super().request_host()
        return urlparse(request_origin(self.request)).hostname

    def request_port(self):
        if not self.request:
            return super().request_port()
        return urlparse(request_origin(self.request)).port

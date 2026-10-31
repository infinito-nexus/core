"""Weblate's proxy middleware on the network sibling a request came in on.

Upstream ``ProxyMiddleware`` pins the request's ``_current_scheme_host`` to
``get_site_url()``, so every absolute URL names the clearnet host. The subclass
keeps upstream's client-address handling and takes scheme and host from the
request instead.
"""

from weblate.middleware import ProxyMiddleware
from weblate_network_strategy import SCHEME_HOST_ATTRIBUTE, request_origin


class NetworkProxyMiddleware(ProxyMiddleware):
    def process_request(self, request):
        response = super().process_request(request)
        request.__dict__[SCHEME_HOST_ATTRIBUTE] = request_origin(request)
        return response

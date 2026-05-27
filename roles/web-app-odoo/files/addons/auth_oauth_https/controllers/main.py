# Part of Infinito.Nexus. See LICENSE file for full copyright and licensing details.

import json
import logging

import werkzeug.urls
from odoo.addons.auth_oauth.controllers.main import OAuthLogin
from odoo.http import request

_logger = logging.getLogger(__name__)


class OAuthLoginHTTPS(OAuthLogin):
    """
    Override OAuth login to force HTTPS redirect URIs using web.base.url.

    The standard auth_oauth module uses request.httprequest.url_root to build
    redirect URIs. When running behind a reverse proxy with TLS termination,
    this may incorrectly return HTTP URLs even if X-Forwarded-Proto is set.

    This override uses the web.base.url system parameter instead, which is
    explicitly configured to the correct HTTPS URL during deployment.
    """

    def _get_base_url(self):
        """
        Get the base URL from web.base.url system parameter.

        Returns the configured web.base.url, or falls back to
        request.httprequest.url_root if not set.
        """
        try:
            base_url = (
                request.env["ir.config_parameter"].sudo().get_param("web.base.url")
            )
            if base_url:
                # Ensure trailing slash for consistency
                if not base_url.endswith("/"):
                    base_url += "/"
                return base_url
        except Exception:
            _logger.exception(
                "Failed to read 'web.base.url' from ir.config_parameter; falling back to request URL root."
            )
        # Fallback to standard behavior
        return request.httprequest.url_root

    def list_providers(self):
        """
        Override list_providers to use web.base.url for redirect URI.

        This ensures OAuth redirect URIs always use the configured HTTPS URL
        instead of potentially incorrect HTTP URLs from request detection.
        """
        try:
            providers = (
                request.env["auth.oauth.provider"]
                .sudo()
                .search_read([("enabled", "=", True)])
            )
        except Exception:
            providers = []

        base_url = self._get_base_url()
        return_url = base_url.rstrip("/") + "/auth_oauth/signin"

        for provider in providers:
            state = self.get_state(provider)
            params = {
                "response_type": "token",
                "client_id": provider["client_id"],
                "redirect_uri": return_url,
                "scope": provider["scope"],
                "state": json.dumps(state),
            }
            provider["auth_link"] = "{}?{}".format(
                provider["auth_endpoint"],
                werkzeug.urls.url_encode(params),
            )

        return providers

    def get_state(self, provider):
        """
        Override get_state to use web.base.url for redirect parameter.

        Ensures the 'r' (redirect) parameter in OAuth state also uses
        the configured HTTPS base URL.
        """
        redirect = request.params.get("redirect") or "web"
        base_url = self._get_base_url()

        if not redirect.startswith(("//", "http://", "https://")):
            redirect = "{}{}".format(
                base_url.rstrip("/") + "/",
                redirect.removeprefix("/"),
            )

        state = {
            "d": request.session.db,
            "p": provider["id"],
            "r": werkzeug.urls.url_quote_plus(redirect),
        }
        token = request.params.get("token")
        if token:
            state["t"] = token
        return state

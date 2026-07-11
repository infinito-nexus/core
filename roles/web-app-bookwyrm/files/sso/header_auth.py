"""Trusted-header SSO bridge for BookWyrm.

BookWyrm core has no OIDC/SSO login. In Infinito.Nexus it sits behind an
oauth2-proxy that authenticates the visitor against Keycloak (OIDC, or LDAP
federated through Keycloak) and forwards the resolved identity to this upstream
as request headers. This module turns that trusted header into a real BookWyrm
session via Django's RemoteUser machinery, auto-provisioning a local BookWyrm
account on first sign-in.

Security: the identity header is trusted unconditionally. This is only safe
because BookWyrm is reachable exclusively through the oauth2-proxy, which
overwrites the header on every request; the application port is bound to the
internal container network. The bridge activates only when PROXY_HEADER_SSO is
truthy (wired by the role's env template behind the oauth2 SSO flavor).

Only the ``X-Forwarded-*`` headers nginx overwrites are read; the
``X-Auth-Request-*``/``Remote-User`` variants are deliberately excluded so a
client cannot inject an identity nginx did not set.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import RemoteUserBackend
from django.contrib.auth.middleware import PersistentRemoteUserMiddleware

CANONICAL_HEADER = "HTTP_X_FORWARDED_PREFERRED_USERNAME"

CANDIDATE_USERNAME_HEADERS = (
    "HTTP_X_FORWARDED_PREFERRED_USERNAME",
    "HTTP_X_FORWARDED_USER",
)

CANDIDATE_EMAIL_HEADERS = ("HTTP_X_FORWARDED_EMAIL",)


def _first_header(meta, names):
    for name in names:
        value = meta.get(name)
        if value:
            return value
    return None


def _localname(remote_user):
    return remote_user.split("@", 1)[0].lower()


class ProxyHeaderMiddleware(PersistentRemoteUserMiddleware):
    """Authenticate from the oauth2-proxy identity header.

    Persistent (does not log the user out when the header is absent), so
    requests that legitimately bypass the proxy — health checks, the
    collectstatic boot step — never clobber an existing session.
    """

    header = CANONICAL_HEADER

    def process_request(self, request):
        if not request.META.get(self.header):
            value = _first_header(request.META, CANDIDATE_USERNAME_HEADERS)
            if value:
                request.META[self.header] = value
        return super().process_request(request)


class ProxyHeaderBackend(RemoteUserBackend):
    """Map the proxied username to a local BookWyrm user, creating it if new."""

    create_unknown_user = True

    def clean_username(self, username):
        return f"{_localname(username)}@{settings.DOMAIN}"

    def authenticate(self, request, remote_user):
        if not remote_user:
            return None
        localname = _localname(remote_user)
        user_model = get_user_model()
        try:
            return self._existing(user_model, localname)
        except user_model.DoesNotExist:
            if not self.create_unknown_user:
                return None
            user = self._provision(request, user_model, localname)
            return user if self.user_can_authenticate(user) else None

    @staticmethod
    def _existing(user_model, localname):
        user = user_model.objects.get(localname__iexact=localname, local=True)
        if not user.is_active:
            user_model.objects.filter(pk=user.pk).update(is_active=True)
            user.refresh_from_db()
        return user

    @staticmethod
    def _provision(request, user_model, localname):
        username = f"{localname}@{settings.DOMAIN}"
        email = _first_header(request.META, CANDIDATE_EMAIL_HEADERS) or username
        return user_model.objects.create_user(
            username,
            email,
            None,
            localname=localname,
            local=True,
            is_active=True,
        )

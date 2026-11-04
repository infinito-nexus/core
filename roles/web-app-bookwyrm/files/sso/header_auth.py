"""Trusted-header SSO bridge for BookWyrm.

BookWyrm core has no OIDC/SSO login. In Infinito.Nexus it sits behind an
oauth2-proxy that authenticates the visitor against Keycloak (OIDC, or LDAP
federated through Keycloak) and forwards the resolved identity to this upstream
as request headers. This module turns that trusted header into a real BookWyrm
session via Django's RemoteUser machinery, auto-provisioning a local BookWyrm
account on first sign-in.

Security: the identity header is trusted unconditionally, so openresty is the
only trust boundary: every front-proxy location must clear or overwrite it.
Anything that reaches the application port without passing openresty can
impersonate any user, and that port is published on DOCKER_BIND_HOST (0.0.0.0
under DOCKER_IN_CONTAINER) and, in swarm, on every node through the routing
mesh. The bridge activates only when PROXY_HEADER_SSO is truthy (wired by the
role's env template behind the oauth2 SSO flavor).

Only the ``X-Forwarded-*`` headers nginx overwrites are read; the
``X-Auth-Request-*``/``Remote-User`` variants are deliberately excluded so a
client cannot inject an identity nginx did not set. Name, language and time
zone come from ``X-Forwarded-Name``/``-Locale``/``-Zoneinfo``, which the gate
forwards from the ID token because ``meta/services.yml`` lists them in
``sso.oauth2.claim_headers``; they are applied on every sign-in.

Environment (set by the role's env template whenever PROXY_HEADER_SSO is on):
    PROXY_HEADER_SSO_GROUP_MAP: JSON object, groups claim path -> BookWyrm group.
    PROXY_HEADER_SSO_BOOTSTRAP_ADMIN: localname of the account the deploy
        converges itself, which the bridge never changes.
"""

import hashlib
import json
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import RemoteUserBackend
from django.contrib.auth.middleware import PersistentRemoteUserMiddleware

CANONICAL_HEADER = "HTTP_X_FORWARDED_PREFERRED_USERNAME"

CANDIDATE_EMAIL_HEADERS = ("HTTP_X_FORWARDED_EMAIL",)

GROUPS_HEADER = "HTTP_X_FORWARDED_GROUPS"
NAME_HEADER = "HTTP_X_FORWARDED_NAME"
LOCALE_HEADER = "HTTP_X_FORWARDED_LOCALE"
ZONEINFO_HEADER = "HTTP_X_FORWARDED_ZONEINFO"

GROUP_MAP_ENV = "PROXY_HEADER_SSO_GROUP_MAP"
BOOTSTRAP_ADMIN_ENV = "PROXY_HEADER_SSO_BOOTSTRAP_ADMIN"

STAFF_GROUPS = frozenset({"admin"})
SESSION_KEY = "infinito_sso_identity"


def _first_header(meta, names):
    for name in names:
        value = meta.get(name)
        if value:
            return value
    return None


def _localname(remote_user):
    return remote_user.split("@", 1)[0].lower()


def desired_groups(groups_header, group_map):
    """Return the BookWyrm groups the forwarded groups claim grants.

    Args:
        groups_header: comma separated groups claim forwarded by the proxy.
        group_map: groups claim path -> BookWyrm group name.
    """
    paths = {path.strip() for path in (groups_header or "").split(",") if path.strip()}
    return {group for path, group in group_map.items() if path in paths}


def language_for(locale):
    """Return the BookWyrm language code that matches an OIDC ``locale``, or None.

    Args:
        locale: the forwarded ``locale`` claim, e.g. ``de`` or ``pt-BR``.
    """
    wanted = (locale or "").strip().replace("_", "-").lower()
    if not wanted:
        return None
    codes = [code for code, _ in settings.LANGUAGES]
    for code in codes:
        if code.lower() == wanted:
            return code
    primary = wanted.split("-", 1)[0]
    for code in codes:
        if code.lower().split("-", 1)[0] == primary:
            return code
    return None


def timezone_for(zoneinfo):
    """Return the forwarded IANA ``zoneinfo`` when it names a known zone, or None.

    Args:
        zoneinfo: the forwarded ``zoneinfo`` claim.
    """
    name = (zoneinfo or "").strip()
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


def identity_from_request(request, group_map):
    """Return the groups and profile fields the proxy forwards for one request.

    Args:
        request: the Django request.
        group_map: the ``PROXY_HEADER_SSO_GROUP_MAP`` mapping.
    """
    return {
        "groups": sorted(desired_groups(request.META.get(GROUPS_HEADER), group_map)),
        "name": (request.META.get(NAME_HEADER) or "").strip() or None,
        "language": language_for(request.META.get(LOCALE_HEADER)),
        "timezone": timezone_for(request.META.get(ZONEINFO_HEADER)),
    }


def apply_identity(user, identity, group_map):
    """Converge one local user to the forwarded identity; return True on change.

    Args:
        user: the authenticated BookWyrm user.
        identity: the mapping returned by ``identity_from_request``.
        group_map: the ``PROXY_HEADER_SSO_GROUP_MAP`` mapping.
    """
    managed = set(group_map.values())
    current = set(user.groups.values_list("name", flat=True))
    target = (current - managed) | set(identity["groups"])
    changed = False
    if target != current:
        user.groups.set(user.groups.model.objects.filter(name__in=target))
        changed = True

    fields = {}
    if not user.is_superuser:
        fields["is_staff"] = bool(target & STAFF_GROUPS)
    for field, key in (
        ("name", "name"),
        ("preferred_language", "language"),
        ("preferred_timezone", "timezone"),
    ):
        if identity[key]:
            fields[field] = identity[key]

    dirty = {key: value for key, value in fields.items() if getattr(user, key) != value}
    if dirty:
        for key, value in dirty.items():
            setattr(user, key, value)
        user.save(broadcast="name" in dirty)
        changed = True
    return changed


def sync_identity(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not getattr(user, "local", False):
        return
    if user.localname.lower() == os.environ[BOOTSTRAP_ADMIN_ENV].lower():
        return
    group_map = json.loads(os.environ[GROUP_MAP_ENV])
    identity = identity_from_request(request, group_map)
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()
    session = getattr(request, "session", None)
    if session is not None and session.get(SESSION_KEY) == fingerprint:
        return

    apply_identity(user, identity, group_map)
    if session is not None:
        session[SESSION_KEY] = fingerprint


class ProxyHeaderMiddleware(PersistentRemoteUserMiddleware):
    """Authenticate from the oauth2-proxy identity header.

    Persistent (does not log the user out when the header is absent), so
    requests that legitimately bypass the proxy — health checks, the
    collectstatic boot step — never clobber an existing session.
    """

    header = CANONICAL_HEADER

    def process_request(self, request):
        result = super().process_request(request)
        if request.META.get(self.header):
            sync_identity(request)
        return result


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

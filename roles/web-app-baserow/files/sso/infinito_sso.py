"""Trusted-header SSO bridge for Baserow.

Infinito.Nexus gates Baserow with oauth2-proxy and forwards the verified
Keycloak identity as request headers. Baserow's web frontend still needs native
Baserow JWT tokens, so this module provisions or repairs a local Baserow user
and returns the same token payload as Baserow's own login endpoint.

Only the ``X-Forwarded-*`` identity headers are read; nginx overwrites those
from the oauth2-proxy auth response on every request, so a client cannot forge
them. The ``X-Auth-Request-*``/``Remote-User``/``X-Forwarded-Name`` variants are
deliberately excluded: nginx does not overwrite them, so reading them would let
an already-authenticated user inject a different identity.
"""

import os
from urllib.parse import urlencode, urlsplit

from baserow.api.user.serializers import log_in_user
from baserow.core.models import (
    WORKSPACE_USER_PERMISSION_ADMIN,
    UserProfile,
    Workspace,
    WorkspaceUser,
)
from baserow.core.user.handler import UserHandler
from baserow.core.user.utils import normalize_email_address
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect
from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

TRUE_VALUES = {"true", "1", "yes", "on"}

USERNAME_HEADERS = (
    "HTTP_X_FORWARDED_PREFERRED_USERNAME",
    "HTTP_X_FORWARDED_USER",
)
EMAIL_HEADERS = ("HTTP_X_FORWARDED_EMAIL",)
NAME_HEADERS = ("HTTP_X_FORWARDED_PREFERRED_USERNAME",)
GROUP_HEADERS = ("HTTP_X_FORWARDED_GROUPS",)

User = get_user_model()


def _sso_enabled():
    return os.environ.get("PROXY_HEADER_SSO", "").lower() in TRUE_VALUES


def _first_header(meta, names):
    for name in names:
        value = meta.get(name)
        if value:
            value = str(value).strip()
            if value:
                return value
    return None


def _fallback_domain():
    raw_domain = (
        os.environ.get("PROXY_HEADER_SSO_FALLBACK_EMAIL_DOMAIN")
        or getattr(settings, "PUBLIC_WEB_FRONTEND_HOSTNAME", "")
        or "localhost"
    )
    parsed = urlsplit(raw_domain if "://" in raw_domain else f"//{raw_domain}")
    return (parsed.hostname or "localhost").strip() or "localhost"


def _email_from_identity(username, header_email):
    if header_email:
        return normalize_email_address(header_email)
    if username and "@" in username:
        return normalize_email_address(username)
    local = "".join(
        char if char.isalnum() or char in "._+-" else "."
        for char in (username or "sso-user")
    ).strip(".")
    return normalize_email_address(f"{local or 'sso-user'}@{_fallback_domain()}")


def _display_name(username, email, header_name):
    raw_name = header_name or username or email.split("@", 1)[0]
    name = " ".join(raw_name.replace(".", " ").replace("_", " ").split())
    if len(name) < 2:
        name = email
    return name[:150]


def _split_groups(raw):
    if not raw:
        return []
    groups = []
    for chunk in str(raw).split(","):
        groups.extend(part for part in chunk.split() if part)
    return groups


def _group_matches(left, right):
    left = (left or "").strip()
    right = (right or "").strip()
    return left == right or left.lstrip("/") == right.lstrip("/")


def _is_admin(groups):
    admin_group = os.environ.get("PROXY_HEADER_SSO_ADMIN_GROUP", "").strip()
    return bool(admin_group) and any(
        _group_matches(group, admin_group) for group in groups
    )


def _identity_from_request(request):
    if not _sso_enabled():
        raise Http404

    username = _first_header(request.META, USERNAME_HEADERS)
    header_email = _first_header(request.META, EMAIL_HEADERS)
    if not username and not header_email:
        raise PermissionDenied("Missing trusted SSO identity header.")

    email = _email_from_identity(username, header_email)
    groups = _split_groups(_first_header(request.META, GROUP_HEADERS))
    return {
        "username": username,
        "email": email,
        "name": _display_name(
            username,
            email,
            _first_header(request.META, NAME_HEADERS),
        ),
        "is_admin": _is_admin(groups),
    }


def _ensure_profile(user):
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"language": settings.LANGUAGE_CODE},
    )
    profile_updates = []
    if profile.email_verified is not True:
        profile.email_verified = True
        profile_updates.append("email_verified")
    if profile.completed_onboarding is not True:
        profile.completed_onboarding = True
        profile_updates.append("completed_onboarding")
    if profile.completed_guided_tours is None:
        profile.completed_guided_tours = []
        profile_updates.append("completed_guided_tours")
    if profile_updates:
        profile.save(update_fields=profile_updates)
    return profile


def _ensure_workspace(user, name):
    workspace_user = (
        WorkspaceUser.objects.select_related("workspace")
        .filter(user=user)
        .order_by("order", "id")
        .first()
    )
    if workspace_user is None:
        workspace = Workspace.objects.create(name=f"{name}'s workspace")
        workspace_user = WorkspaceUser.objects.create(
            workspace=workspace,
            user=user,
            order=WorkspaceUser.get_last_order(user),
            permissions=WORKSPACE_USER_PERMISSION_ADMIN,
        )
    user.default_workspace = workspace_user.workspace


@transaction.atomic
def _get_or_create_user(identity):
    email = identity["email"]
    username = identity["username"]
    user_query = Q(email__iexact=email) | Q(username__iexact=email)
    if username:
        user_query |= Q(username__iexact=username)

    user = User.objects.select_for_update().filter(user_query).order_by("id").first()
    if user is None:
        user = UserHandler().force_create_user(
            email=email,
            name=identity["name"],
            password=None,
            is_staff=identity["is_admin"],
            is_superuser=identity["is_admin"],
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])

    user_updates = []
    if not user.is_active:
        user.is_active = True
        user_updates.append("is_active")
    if not user.email:
        user.email = email
        user_updates.append("email")
    if not user.first_name or len(user.first_name) < 2:
        user.first_name = identity["name"]
        user_updates.append("first_name")
    if identity["is_admin"] and not user.is_staff:
        user.is_staff = True
        user_updates.append("is_staff")
    if identity["is_admin"] and not user.is_superuser:
        user.is_superuser = True
        user_updates.append("is_superuser")
    if user_updates:
        user.save(update_fields=user_updates)

    _ensure_profile(user)
    _ensure_workspace(user, identity["name"])
    return user


def _login_payload(request):
    user = _get_or_create_user(_identity_from_request(request))
    return log_in_user(request, user)


def _safe_next_url(request):
    next_url = request.GET.get("next") or "/"
    next_url = next_url.replace("\\", "/")
    parsed = urlsplit(next_url)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


class ProxyHeaderTokenView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        return Response(_login_payload(request))

    def post(self, request):
        return Response(_login_payload(request))


class ProxyHeaderLoginView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        payload = _login_payload(request)
        query = urlencode(
            {
                "token": payload["refresh_token"],
                "user_session": payload["user_session"],
            }
        )
        next_url = _safe_next_url(request)
        separator = "&" if "?" in next_url else "?"
        return redirect(f"{next_url}{separator}{query}")


app_name = "baserow.infinito_sso"

urlpatterns = [
    path("login/", ProxyHeaderLoginView.as_view(), name="login"),
    path("token/", ProxyHeaderTokenView.as_view(), name="token"),
]

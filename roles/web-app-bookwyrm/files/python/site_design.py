"""Converge the BookWyrm administrator, the site title, logos and the corporate theme.

Runs inside ``manage.py shell`` with this file on stdin.

Environment:
    ADMIN_USERNAME: localname of the platform administrator.
    ADMIN_EMAIL: e-mail of the administrator.
    ADMIN_PASSWORD: password the account converges on.
    DESIGN_STATE: "present" registers the corporate theme, title and logos, "absent" removes them.
    SITE_NAME: instance name shown in titles and on the landing page.
    THEME_NAME: display name of the corporate theme.
    THEME_PATH: static path of the corporate theme.
    LOGO_SMALL: base64 PNG for the navigation logo, empty to leave it alone.
    LOGO: base64 PNG for the touch icon and preview logo, empty to leave it alone.
    FAVICON: base64 ICO for the favicon, empty to leave it alone.

Prints ``BOOKWYRM_RESULT=CHANGED`` or ``BOOKWYRM_RESULT=UNCHANGED``.
"""

import base64
import hashlib
import os
from pathlib import PurePosixPath

from bookwyrm import models, settings
from bookwyrm.activitypub import get_representative
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile

LOCALNAME = os.environ["ADMIN_USERNAME"]
EMAIL = os.environ["ADMIN_EMAIL"]
PASSWORD = os.environ["ADMIN_PASSWORD"]
PRESENT = os.environ["DESIGN_STATE"] == "present"
SITE_NAME = os.environ["SITE_NAME"]
THEME_NAME = os.environ["THEME_NAME"]
THEME_PATH = os.environ["THEME_PATH"]
MARK = "infinito-"
IMAGES = {
    "logo_small": ("LOGO_SMALL", "png"),
    "logo": ("LOGO", "png"),
    "favicon": ("FAVICON", "ico"),
}
ADMIN_GROUPS = ["admin", "moderator"]


def converge_admin():
    user = models.User.objects.filter(localname__iexact=LOCALNAME, local=True).first()
    if user is None:
        user = models.User.objects.create_superuser(
            f"{LOCALNAME}@{settings.DOMAIN}",
            EMAIL,
            PASSWORD,
            localname=LOCALNAME,
            local=True,
            deactivation_reason=None,
            is_active=True,
            two_factor_auth=False,
            show_guided_tour=False,
        )
        user.groups.set(Group.objects.filter(name__in=ADMIN_GROUPS))
        return True
    groups = set(user.groups.values_list("name", flat=True))
    dirty = (
        not user.check_password(PASSWORD)
        or not (user.is_superuser and user.is_staff and user.is_active)
        or user.two_factor_auth is None
        or not set(ADMIN_GROUPS) <= groups
    )
    if dirty:
        user.set_password(PASSWORD)
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        if user.two_factor_auth is None:
            user.two_factor_auth = False
        user.save(broadcast=False)
        user.groups.add(*Group.objects.filter(name__in=ADMIN_GROUPS))
    return dirty


def converge_image(site, field, payload, extension):
    current = getattr(site, field)
    name = PurePosixPath(current.name).name if current else ""
    ours = name.startswith(MARK)
    if not PRESENT or not payload:
        if not ours:
            return False
        current.delete(save=False)
        return True
    data = base64.b64decode(payload)
    stem = f"{MARK}{field.replace('_', '-')}-{hashlib.sha256(data).hexdigest()[:12]}"
    if name.startswith(stem):
        return False
    if current and ours:
        current.delete(save=False)
    current.save(f"{stem}.{extension}", ContentFile(data), save=False)
    return True


def converge_site(site):
    dirty = False
    if site.install_mode:
        site.install_mode = False
        dirty = True
    if PRESENT and SITE_NAME and site.name != SITE_NAME:
        site.name = SITE_NAME
        dirty = True
    for field, (variable, extension) in IMAGES.items():
        dirty = converge_image(site, field, os.environ[variable], extension) or dirty
    if dirty:
        site.save()
        get_representative()
    return dirty


def converge_theme(site):
    ours = models.Theme.objects.filter(path=THEME_PATH).first()
    if not PRESENT:
        if ours is None:
            return False
        ours.delete()
        return True
    dirty = False
    if ours is None:
        ours = models.Theme.objects.create(name=THEME_NAME, path=THEME_PATH, loads=True)
        dirty = True
    if site.default_theme_id is None:
        site.default_theme = ours
        site.save(update_fields=["default_theme"])
        dirty = True
    return dirty


changed = converge_admin()
site = models.SiteSettings.get()
changed = converge_site(site) or changed
changed = converge_theme(models.SiteSettings.get()) or changed
print("BOOKWYRM_RESULT=" + ("CHANGED" if changed else "UNCHANGED"))

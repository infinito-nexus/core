"""Environment:
    WEBLATE_LOGIN_2FA_ENFORCED: ``1`` while the deploy enforces the second
        factor, ``0`` while it does not.

Output:
    ``main()`` prints ``CHANGED <n>``, n = flags switched.
"""

import json
import os
from pathlib import Path

from weblate.utils.celery import app

ENFORCED = "WEBLATE_LOGIN_2FA_ENFORCED"
GUESTS = "Guests"


def plan(enforced, current, owned):
    """Args:
        enforced: whether the deploy enforces the second factor.
        current: ``{pk: enforced_2fa}`` of every object in scope.
        owned: pks whose flag the deploy switched on.

    Returns:
        The pks to switch, the value to switch them to, and the pks the
        deploy owns afterwards.
    """
    if enforced:
        switch = sorted(pk for pk, on in current.items() if not on)
        return switch, True, sorted(set(switch) | (set(owned) & set(current)))
    return sorted(pk for pk in set(owned) & set(current) if current[pk]), False, []


def scopes():
    """Returns:
    ``{scope: queryset}`` of the teams and projects whose flag the deploy
    manages.
    """
    from weblate.auth.models import Group
    from weblate.trans.models import Project

    return {
        "teams": Group.objects.filter(defining_project__isnull=True).exclude(
            name=GUESTS
        ),
        "projects": Project.objects.all(),
    }


def converge(enforced, marker):
    """Args:
        enforced: whether the deploy enforces the second factor.
        marker: JSON file holding the pks the deploy switched on per scope.

    Returns:
        The number of flags switched.
    """
    stored = marker.read_text() if marker.exists() else "{}"
    owned = json.loads(stored)
    switched = 0
    for scope, objects in scopes().items():
        switch, value, owned[scope] = plan(
            enforced,
            dict(objects.values_list("pk", "enforced_2fa")),
            owned.get(scope, []),
        )
        switched += objects.filter(pk__in=switch).update(enforced_2fa=value)
    text = json.dumps(owned, sort_keys=True)
    if text != stored:
        marker.parent.mkdir(exist_ok=True)
        staged = marker.with_suffix(".tmp")
        staged.write_text(text)
        staged.replace(marker)
    return switched


def enforced():
    return {"1": True, "0": False}[os.environ[ENFORCED]]


def marker():
    from django.conf import settings

    return Path(settings.DATA_DIR, "infinito", "enforced_2fa.json")


def main():
    print(f"CHANGED {converge(enforced(), marker())}")


@app.task(trail=False)
def enforce_two_factor():
    converge(enforced(), marker())


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        3600, enforce_two_factor.s(), name="infinito-enforce-two-factor"
    )

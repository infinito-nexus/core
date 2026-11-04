"""Converge the RBAC teams of every Pretix organizer and their pretix-oidc assignment rules.

Environment:
    RBAC_CLAIM:     ID token claim the assignment rules read.
    RBAC_TEAMS:     JSON list of {name, group, all_event_permissions,
                    limit_event_permissions, all_organizer_permissions}.
    ORGANIZER_NAME: name of the organizer created when none exists.
    ORGANIZER_SLUG: slug of the organizer created when none exists.

Output:
    PRETIX_RESULT=CHANGED or PRETIX_RESULT=UNCHANGED on its own line.
"""

import json
import os
import sys
import traceback

from pretix.base.models import Organizer
from pretix.base.models.organizer import Team
from pretix_oidc.models import OIDCTeamAssignmentRule

CLAIM = os.environ["RBAC_CLAIM"]
TEAMS = json.loads(os.environ["RBAC_TEAMS"])
ORGANIZER_NAME = os.environ["ORGANIZER_NAME"]
ORGANIZER_SLUG = os.environ["ORGANIZER_SLUG"]


def converge():
    changed = False
    if not Organizer.objects.exists():
        organizer = Organizer(name=ORGANIZER_NAME, slug=ORGANIZER_SLUG)
        organizer.full_clean()
        organizer.save()
        changed = True
    for organizer in Organizer.objects.order_by("slug"):
        for spec in TEAMS:
            wanted = {
                "all_events": True,
                "all_event_permissions": spec["all_event_permissions"],
                "limit_event_permissions": spec["limit_event_permissions"],
                "all_organizer_permissions": spec["all_organizer_permissions"],
                "limit_organizer_permissions": {},
            }
            team, created = Team.objects.get_or_create(
                organizer=organizer, name=spec["name"], defaults=wanted
            )
            drift = {k: v for k, v in wanted.items() if getattr(team, k) != v}
            for key, value in drift.items():
                setattr(team, key, value)
            if drift:
                team.save()
            _, rule_created = OIDCTeamAssignmentRule.objects.get_or_create(
                team=team, attribute=CLAIM, value=spec["group"]
            )
            stale, _ = (
                OIDCTeamAssignmentRule.objects.filter(team=team)
                .exclude(attribute=CLAIM, value=spec["group"])
                .delete()
            )
            changed = changed or created or bool(drift) or rule_created or stale > 0
    return "CHANGED" if changed else "UNCHANGED"


def report():
    try:
        line = "PRETIX_RESULT=" + converge()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    print(line, flush=True)


report()

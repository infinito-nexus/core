# nocheck: mirrored-unit-test - imports pretix.base.models at module level and runs its
# queries inside `pretix shell_scoped`, where django-scopes supplies the scope; the
# models are not importable outside the Pretix image
"""Give the MCP adapter a read-only team token in every Pretix organizer.

Runs inside ``pretix shell_scoped --override``: teams and events are
django-scopes-scoped, so an unscoped query raises rather than returning
everything.

Pretix has no API endpoint for creating team tokens, only the web UI, and the
model takes an explicit value, so the deployment pins its own credential rather
than capturing a generated one.

A token belongs to a team and a team belongs to an organizer. The adapter
presents exactly one token, and the same value in two organizers would make
Pretix's token lookup return two rows and answer 500, so the token is pinned in
a single organizer chosen deterministically by slug. With no organizer there is
nothing to attach it to, and no tool call could name one either, so that case
converges to a no-op instead of failing.

``shell_scoped`` feeds this to IPython, which executes an indented block only
once a dedented line follows it. A block that ends the input is left unrun, and
the last line of the output is IPython's exit prompt rather than a result, so
the final statement is a top-level print of a marker the task matches on.

Environment:
    MCP_TEAM:  team name to converge.
    MCP_TOKEN: token value to pin on it.

Output:
    PRETIX_RESULT=CHANGED or PRETIX_RESULT=UNCHANGED on its own line.
"""

import os

from pretix.base.models import Organizer
from pretix.base.models.organizer import Team, TeamAPIToken

TEAM = os.environ["MCP_TEAM"]
TOKEN = os.environ["MCP_TOKEN"]
TOKEN_NAME = "mcp-upstream"  # noqa: S105 a label, not a secret

changed = False

organizer = Organizer.objects.order_by("slug").first()
if organizer is not None:
    team, created = Team.objects.get_or_create(
        organizer=organizer,
        name=TEAM,
        defaults={
            "all_events": True,
            "all_event_permissions": False,
            "limit_event_permissions": {"event.orders:read": True},
            "all_organizer_permissions": False,
            "limit_organizer_permissions": {},
        },
    )
    changed = changed or created

    _, created = TeamAPIToken.objects.update_or_create(
        team=team,
        name=TOKEN_NAME,
        defaults={"token": TOKEN, "active": True},
    )
    changed = changed or created

print("PRETIX_RESULT=CHANGED" if changed else "PRETIX_RESULT=UNCHANGED")

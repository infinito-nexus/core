# nocheck: mirrored-unit-test - imports pretix.base.models at module level and runs inside
# `pretix shell_scoped`; the models are not importable outside the Pretix image
"""Converge the corporate shop colors on the global settings layer of Pretix.

Environment:
    DESIGN_STATE:  ``present`` sets the colors, ``absent`` removes the ones
                   this script set and nobody changed since.
    DESIGN_COLORS: JSON object of setting key to ``#rrggbb`` value.

Prints ``PRETIX_RESULT=CHANGED`` or ``PRETIX_RESULT=UNCHANGED``.
"""

import json
import os

from pretix.base.models import Organizer
from pretix.base.settings import GlobalSettingsObject

MARK = "infinito_design_colors"
WANTED = json.loads(os.environ["DESIGN_COLORS"])
PRESENT = os.environ["DESIGN_STATE"] == "present"


def converge():
    settings = GlobalSettingsObject().settings
    settings.flush()
    stored = dict(settings._cache())
    mark = json.loads(stored.get(MARK) or "{}")
    changed = False
    if PRESENT:
        for key, value in WANTED.items():
            if stored.get(key) != value:
                settings.set(key, value)
                changed = True
        if mark != WANTED:
            settings.set(MARK, json.dumps(WANTED, sort_keys=True))
            changed = True
    elif mark:
        for key, value in mark.items():
            if stored.get(key) == value:
                settings.delete(key)
        settings.delete(MARK)
        changed = True
    if changed:
        for organizer in Organizer.objects.all():
            organizer.cache.clear()
    return "CHANGED" if changed else "UNCHANGED"


print("PRETIX_RESULT=" + converge())

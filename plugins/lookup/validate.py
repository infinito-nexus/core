from __future__ import annotations

from plugins.lookup.debug import ModeSwitchLookup


class LookupModule(ModeSwitchLookup):
    SWITCH = "validate"
    GLOBAL = "VALIDATE"

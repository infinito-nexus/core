FIELDS = ("name", "providerId", "enabled", "defaultAction", "priority")


def kc_drifted_required_actions(desired, current):
    """Return the desired required actions whose live state differs.

    Args:
        desired: required actions of the realm dictionary.
        current: required actions Keycloak holds, matched by alias.

    Returns:
        The ``desired`` actions that are absent from ``current``, or whose
        fields or config values differ from it.
    """
    held = {action["alias"]: action for action in current}
    drifted = []
    for action in desired:
        live = held.get(action["alias"])
        if live is None or any(live.get(key) != action.get(key) for key in FIELDS):
            drifted.append(action)
            continue
        live_config = live.get("config") or {}
        if any(
            str(live_config.get(key)) != str(value)
            for key, value in (action.get("config") or {}).items()
        ):
            drifted.append(action)
    return drifted


class FilterModule:
    def filters(self):
        return {"kc_drifted_required_actions": kc_drifted_required_actions}

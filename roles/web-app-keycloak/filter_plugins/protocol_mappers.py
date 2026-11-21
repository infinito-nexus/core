def _config_matches(desired, current):
    return all(str(current.get(key)) == str(value) for key, value in desired.items())


def kc_drifted_protocol_mappers(current, desired):
    """Return the live protocol mappers whose definition left the desired one.

    Args:
        current: protocol mappers Keycloak holds, each with id, name,
            protocolMapper and config.
        desired: protocol mappers of the realm dictionary, matched by name.

    Returns:
        The ``current`` mappers whose type differs from or whose config lacks a
        value of the desired mapper of the same name.
    """
    wanted = {mapper["name"]: mapper for mapper in desired}
    return [
        mapper
        for mapper in current
        if mapper["name"] in wanted
        and (
            mapper.get("protocolMapper") != wanted[mapper["name"]]["protocolMapper"]
            or not _config_matches(
                wanted[mapper["name"]].get("config") or {}, mapper.get("config") or {}
            )
        )
    ]


def kc_missing_protocol_mappers(desired, current, drifted):
    """Return the desired protocol mappers to create.

    Args:
        desired: protocol mappers of the realm dictionary.
        current: protocol mappers Keycloak holds.
        drifted: the ``current`` mappers about to be deleted for drift.

    Returns:
        The ``desired`` mappers whose name no kept ``current`` mapper carries.
    """
    dropped = {mapper["id"] for mapper in drifted}
    kept = {mapper["name"] for mapper in current if mapper["id"] not in dropped}
    return [mapper for mapper in desired if mapper["name"] not in kept]


class FilterModule:
    def filters(self):
        return {
            "kc_drifted_protocol_mappers": kc_drifted_protocol_mappers,
            "kc_missing_protocol_mappers": kc_missing_protocol_mappers,
        }

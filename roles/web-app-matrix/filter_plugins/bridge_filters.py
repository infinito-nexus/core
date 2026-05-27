def filter_enabled_bridges(bridges, plugins):
    """
    Return only those bridge definitions whose 'bridge_name' is set to True in plugins.
    :param bridges: list of dicts, each with a 'bridge_name' key
    :param plugins: dict mapping bridge_name to a boolean
    """
    return [b for b in bridges if plugins.get(b["bridge_name"], False)]


class FilterModule:
    def filters(self):
        return {
            "filter_enabled_bridges": filter_enabled_bridges,
        }

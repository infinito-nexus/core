"""Tell whether a manager or coordination-store group can hold a majority."""

from __future__ import annotations

from utils.roles.db.instances import is_valid_quorum_size


def swarm_quorum_size_valid(count) -> bool:
    """Return True for 0, 1 or an odd member count of at least 3.

    Args:
        count: number of members in the group.
    """
    return is_valid_quorum_size(int(count))


class FilterModule:
    def filters(self):
        return {"swarm_quorum_size_valid": swarm_quorum_size_valid}

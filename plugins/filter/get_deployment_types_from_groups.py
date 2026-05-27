from __future__ import annotations

from utils.roles.validation.invokable import types_from_group_names


def get_deployment_types_from_groups(group_names):
    return types_from_group_names(group_names or [])


class FilterModule:
    def filters(self):
        return {"get_deployment_types_from_groups": get_deployment_types_from_groups}

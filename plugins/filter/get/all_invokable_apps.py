from __future__ import annotations

from utils.roles.validation.invokable import list_invokable_app_ids


def get_all_invokable_apps():
    return list_invokable_app_ids()


class FilterModule:
    def filters(self):
        return {"get_all_invokable_apps": get_all_invokable_apps}

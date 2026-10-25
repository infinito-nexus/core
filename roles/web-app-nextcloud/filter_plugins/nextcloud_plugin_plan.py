from __future__ import annotations


def _flag(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1", "on")


def _setting(plugin: dict, key: str, empty):
    config = plugin.get("config") or {}
    if key in config:
        return config[key]
    return plugin.get(key, empty)


def nextcloud_plugin_plan(plugin_items, app_list):
    """Split the addon entries by the work each one still needs.

    Args:
      plugin_items: ``dict2items`` of the role's ``addons`` config, in order;
        an enabled entry turns its ``incompatible_plugins`` off and itself on,
        a disabled entry turns itself off, and a later entry wins.
      app_list: parsed ``occ app:list --output=json``.

    Returns:
      dict of app ids:
        disable   - wanted off and enabled right now
        install   - wanted on and not installed, or shipped as a pinned archive
        enable    - wanted on, installed, not enabled
        configure - wanted on and already enabled
    """
    enabled_now = set((app_list or {}).get("enabled") or {})
    installed = enabled_now | set((app_list or {}).get("disabled") or {})

    wanted: dict[str, bool] = {}
    for item in plugin_items:
        plugin = item["value"]
        if _flag(plugin.get("enabled", False)):
            for incompatible in _setting(plugin, "incompatible_plugins", []) or []:
                wanted[incompatible] = False
            wanted[item["key"]] = True
        else:
            wanted[item["key"]] = False

    plan = {
        "disable": [app for app, on in wanted.items() if not on and app in enabled_now],
        "install": [],
        "enable": [],
        "configure": [],
    }
    for item in plugin_items:
        key = item["key"]
        if not wanted.get(key):
            continue
        if key not in installed or _setting(item["value"], "archive", ""):
            plan["install"].append(key)
        elif key not in enabled_now:
            plan["enable"].append(key)
        else:
            plan["configure"].append(key)
    return plan


class FilterModule:
    def filters(self):
        return {"nextcloud_plugin_plan": nextcloud_plugin_plan}

from __future__ import annotations

from collections.abc import Mapping

from ansible.plugins.filter.core import to_json

SENSITIVE_VALUE = "***REMOVED SENSITIVE VALUE***"


def nextcloud_occ_value(configvalue) -> str:
    """The string ``occ config:app:set --value`` receives for one entry.

    Args:
      configvalue: the entry's ``configvalue`` as Ansible rendered it.

    Returns:
      JSON for a mapping or a non-string sequence, ``str()`` for the rest.
    """
    sequence = hasattr(configvalue, "__len__") and hasattr(configvalue, "__getitem__")
    if isinstance(configvalue, Mapping) or (
        sequence and not isinstance(configvalue, str)
    ):
        return to_json(configvalue)
    return str(configvalue)


def _held(current, value: str) -> bool:
    if isinstance(current, bool) or current == SENSITIVE_VALUE:
        return False
    if isinstance(current, str):
        return current == value
    if isinstance(current, int):
        return str(current) == value
    return False


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def nextcloud_plugin_config_pending(specs, app_config):
    """The plugin configuration entries ``occ config:app:set`` still has to write.

    Args:
      specs: the addon specs of the plugins to configure, in the order their
        entries are written; ``config.plugin_configuration`` is optional.
      app_config: parsed ``occ config:list --output=json``.

    Returns:
      list of dicts in spec and entry order, one per entry unless Nextcloud
      already holds exactly its ``--value`` as a string or integer; an entry
      with a ``type``, or held masked, as a boolean, float or structure, is
      always returned:
        appid     - the app the key belongs to
        configkey - the key
        type      - the ``--type`` of the entry, None when it has none
        value     - the ``--value`` string
    """
    apps = _mapping(app_config["apps"])
    pending = []
    for spec in specs:
        for item in (spec.get("config") or {}).get("plugin_configuration", []):
            appid = item["appid"]
            configkey = item["configkey"]
            value = nextcloud_occ_value(item["configvalue"])
            typed = "type" in item
            held = _mapping(apps.get(appid))
            if not typed and configkey in held and _held(held[configkey], value):
                continue
            pending.append(
                {
                    "appid": appid,
                    "configkey": configkey,
                    "type": str(item["type"]) if typed else None,
                    "value": value,
                }
            )
    return pending


def nextcloud_occ_config_set_batch(pending):
    """The ``occ config:app:set`` calls that write the pending entries.

    Args:
      pending: ``nextcloud_plugin_config_pending`` entries.

    Returns:
      list of dicts in entry order, the calls files/php/utils/occ_batch.php runs:
        argv  - the ``occ`` arguments; a typed entry adds
                ``--no-interaction --type=<type>``
        label - ``appid/configkey``
    """
    batch = []
    for item in pending:
        typed = (
            ["--no-interaction", "--type=" + item["type"]]
            if item["type"] is not None
            else []
        )
        batch.append(
            {
                "argv": [
                    "config:app:set",
                    item["appid"],
                    item["configkey"],
                    *typed,
                    "--value",
                    item["value"],
                ],
                "label": item["appid"] + "/" + item["configkey"],
            }
        )
    return batch


class FilterModule:
    def filters(self):
        return {
            "nextcloud_plugin_config_pending": nextcloud_plugin_config_pending,
            "nextcloud_occ_config_set_batch": nextcloud_occ_config_set_batch,
        }

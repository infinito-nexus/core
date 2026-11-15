from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

from utils.cache.yaml import load_yaml_str

LOKI_UID = "loki"
PROMETHEUS_UID = "prometheus"


def _first(entries: Any) -> Mapping:
    if isinstance(entries, list) and entries and isinstance(entries[0], Mapping):
        return entries[0]
    return {}


def _by_uid(entries: Any, uid: str) -> Mapping:
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, Mapping) and entry.get("uid") == uid:
            return entry
    return {}


def _held(**found: Any) -> dict[str, str]:
    return {field: value for field, value in found.items() if isinstance(value, str)}


def _datasources(data: Mapping) -> dict[str, str]:
    loki = _by_uid(data.get("datasources"), LOKI_UID)
    secure = loki.get("secureJsonData")
    return _held(
        loki_url=loki.get("url"),
        loki_tenant=secure.get("httpHeaderValue1")
        if isinstance(secure, Mapping)
        else None,
        prometheus_url=_by_uid(data.get("datasources"), PROMETHEUS_UID).get("url"),
    )


def _dashboards(data: Mapping) -> dict[str, str]:
    return _held(folder=_first(data.get("providers")).get("folder"))


def _alerting(data: Mapping) -> dict[str, str]:
    receiver = _first(_first(data.get("contactPoints")).get("receivers"))
    settings = receiver.get("settings")
    query = _first(_first(_first(data.get("groups")).get("rules")).get("data"))
    model = query.get("model")
    return _held(
        alertmanager_url=settings.get("url") if isinstance(settings, Mapping) else None,
        log_alert_expr=model.get("expr") if isinstance(model, Mapping) else None,
    )


READERS = {
    "datasources": _datasources,
    "dashboards": _dashboards,
    "alerting": _alerting,
}


def grafana_provisioned(results: Any) -> dict[str, dict[str, str]]:
    """Return what the provisioning files a previous deploy rendered hold per form.

    Args:
        results: the ``results`` of slurping ``<form>.yml`` for each provisioning
            form, each with its form as ``item``; a file the slurp did not read
            is skipped.

    Returns:
        Each read form mapped to the managed fields its file holds as strings;
        a field the file does not hold is left out.
    """
    held = {}
    for result in results if isinstance(results, list) else []:
        form = result.get("item") if isinstance(result, Mapping) else None
        content = result.get("content") if isinstance(result, Mapping) else None
        if form not in READERS or not isinstance(content, str):
            continue
        data = load_yaml_str(base64.b64decode(content).decode("utf-8"))
        held[form] = READERS[form](data if isinstance(data, Mapping) else {})
    return held


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {"grafana_provisioned": grafana_provisioned}

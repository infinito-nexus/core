# -*- coding: utf-8 -*-
"""
Ansible filter to count active docker services for current host.

Active means:
- application key is in group_names
- application key matches prefix regex (default: ^(web-|svc-).* )
- under applications[app]['services'] each service is counted if:
  - 'enabled' is True, OR
  - 'enabled' is missing/undefined  (treated as active)

Returns an integer. If ensure_min_one=True, returns at least 1.
"""

import re
from typing import Any, Mapping, Iterable


def _is_mapping(x: Any) -> bool:
    # be liberal: Mapping covers dict-like; fallback to dict check
    try:
        return isinstance(x, Mapping)
    except Exception:
        return isinstance(x, dict)


def active_docker_container_count(
    applications: Mapping[str, Any],
    group_names: Iterable[str],
    prefix_regex: str = r"^(web-|svc-).*",
    ensure_min_one: bool = False,
) -> int:
    if not _is_mapping(applications):
        return 1 if ensure_min_one else 0

    group_set = set(group_names or [])
    try:
        pattern = re.compile(prefix_regex)
    except re.error:
        pattern = re.compile(r"^(web-|svc-).*")  # fallback

    count = 0

    for app_key, app_val in applications.items():
        # host selection + name prefix
        if app_key not in group_set:
            continue
        if not pattern.match(str(app_key)):
            continue

        services = app_val.get("services") if _is_mapping(app_val) else None
        if not _is_mapping(services):
            # sometimes roles define a single service name string; ignore
            continue

        for _svc_name, svc_cfg in services.items():
            if not _is_mapping(svc_cfg):
                # allow shorthand like: service: {} or image string -> counts as enabled
                count += 1
                continue
            enabled = svc_cfg.get("enabled", True)
            if isinstance(enabled, bool):
                if enabled:
                    count += 1
            else:
                # non-bool enabled -> treat "truthy" as enabled
                if bool(enabled):
                    count += 1

    if ensure_min_one and count < 1:
        return 1
    return count


class FilterModule(object):
    def filters(self):
        return {
            # usage: {{ lookup('applications') | active_docker_container_count(group_names) }}
            "active_docker_container_count": active_docker_container_count,
        }

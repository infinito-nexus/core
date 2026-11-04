"""Lookup ``cache_upstreams``: the hosts the package cache answers for.

The declarations live under ``cache: hosts:`` in every role's
``meta/networks.yml`` and `utils.cache.hosts` collects them. Deployed, the
inventory may correct or extend them; see `utils.cache.inventory`.

Returns one dict per host, sorted by host, carrying ``host``, ``repo``,
``routes``, ``listen``, ``read_timeout`` and ``passthrough``.
"""

from __future__ import annotations

from typing import Any

from ansible.plugins.lookup import LookupBase

from utils.cache.hosts import host_records
from utils.cache.inventory import configured, merge

SECTION = "upstreams"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        overrides = configured(
            self._loader, getattr(self, "_templar", None), variables, SECTION
        )
        return [list(merge(host_records(), overrides).values())]

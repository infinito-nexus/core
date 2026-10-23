"""Lookup ``cache_repos``: the repositories the package cache proxies.

Keyed by repository name, so a template resolving a host's route reaches its
flavor, upstream and mirror without a second declaration. `utils.cache.hosts`
is the single point of truth; the entries come from ``cache: repos:`` in the
roles' ``meta/networks.yml``, and deployed, the inventory may correct or
extend them; see `utils.cache.inventory`.

    {{ lookup('cache_repos')['apt-debian'].mirror }}
"""

from __future__ import annotations

from typing import Any

from ansible.plugins.lookup import LookupBase

from utils.cache.hosts import repo_records
from utils.cache.inventory import configured, merge

SECTION = "repos"


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
        return [merge(repo_records(), overrides)]

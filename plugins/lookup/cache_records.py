"""Lookup ``cache_records``: the repositories, as the bootstrap script reads them.

The same string `.env` carries as ``INFINITO_CACHE_UPSTREAMS``, so the role's
bootstrap task and the dev stack provision Nexus from one rendering.
`utils.cache.records` owns the format.

    {{ lookup('cache_records') }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.records import MIRRORS_KEY, records


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        rendered = records()
        if not rendered:
            raise AnsibleError(
                f"{MIRRORS_KEY} needs a primary and a fallback mirror before the "
                "apt-ubuntu repositories can be proxied; Nexus would otherwise be "
                "bootstrapped against an unresolved placeholder"
            )
        return [rendered]

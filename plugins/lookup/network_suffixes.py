from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.reachability import NETWORKS


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('network_suffixes') }}

    Returns ``{name: suffix}`` for every registry network that has a suffix.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if terms:
            raise AnsibleError("lookup('network_suffixes') takes no terms")
        return [
            {name: entry.suffix for name, entry in NETWORKS.items() if entry.suffix}
        ]

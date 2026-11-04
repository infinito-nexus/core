"""Redirect mappings fanned out to every network sibling of their source."""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.reachability import network_of


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('network_redirects', web_opt_rdr_domains_mappings) }}

    Returns one ``{source, target}`` mapping per network sibling of each
    source, the first mapping of a source winning. A source without siblings
    is kept as given, and so is the canonical sibling of a source; a further
    sibling is kept only where its target is served in that sibling's network,
    so no vhost redirects into another network. Targets stay canonical; the
    redirect template moves each one into the network of its source.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        mappings = terms[0] if len(terms) == 1 and isinstance(terms[0], list) else terms
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        siblings = lookup_loader.get(
            "network_siblings",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        )
        fanned: list[dict[str, Any]] = []
        seen: set[str] = set()
        for mapping in mappings:
            if not isinstance(mapping, dict) or "source" not in mapping:
                raise AnsibleError(
                    f"network_redirects: expected {{source, target}} mappings, got {mapping!r}"
                )
            source = str(mapping["source"])
            target = str(mapping.get("target") or "")
            target_networks = {
                network_of(host)
                for host in siblings.run([target], variables=variables)[0] or [target]
            }
            for index, sibling in enumerate(
                siblings.run([source], variables=variables)[0] or [source]
            ):
                if sibling in seen:
                    continue
                if index and network_of(sibling) not in target_networks:
                    continue
                seen.add(sibling)
                fanned.append({**mapping, "source": sibling})
        return [fanned]

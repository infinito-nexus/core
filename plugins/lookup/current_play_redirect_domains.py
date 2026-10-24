from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.merge.mapping import merge_mapping
from utils.domains.list import render_domain_value
from utils.networks.reachability import (
    CLEARNET,
    NODE_MODES,
    TOR,
    network_of,
    resolve_node_mode,
    tor_serves_host,
)
from utils.roles.entity.name import entity_name


def _per_app_redirect_mappings(
    apps: Mapping[str, Any],
    primary_domain: str,
    auto_build_alias: bool,
) -> list[dict[str, str]]:
    """Build a flat list of {source, target} 301 mappings for all apps.

    For each app, the canonical (first entry of ``domains.canonical``,
    falling back to ``<entity>.<primary_domain>``) is the redirect target.
    Each alias from ``domains.aliases`` becomes a source. When
    ``auto_build_alias`` is true, ``<entity>.<primary_domain>`` is also
    added as an alias unless already canonical. Self-mappings are skipped.
    """

    def _parse_entry(domains_cfg, key, app_id):
        if key not in domains_cfg:
            return None
        entry = render_domain_value(
            domains_cfg[key],
            {"DOMAIN_PRIMARY": primary_domain},
            f"{app_id}.domains.{key}",
        )
        if isinstance(entry, dict):
            values = list(entry.values())
        elif isinstance(entry, list):
            values = entry
        else:
            raise AnsibleError(
                f"Unexpected type for 'domains.{key}' in application '{app_id}': "
                f"{type(entry).__name__}"
            )
        for d in values:
            if not isinstance(d, str) or not d.strip():
                raise AnsibleError(
                    f"Invalid domain entry in '{key}' for application '{app_id}': {d!r}"
                )
        return values

    def _default_domain(app_id: str) -> str:
        return f"{entity_name(app_id)}.{primary_domain}"

    canonical_map: dict[str, list[str]] = {}
    for app_id, cfg in apps.items():
        domains_cfg = (cfg or {}).get("domains") or {}
        if "canonical" in domains_cfg:
            entry = render_domain_value(
                domains_cfg["canonical"],
                {"DOMAIN_PRIMARY": primary_domain},
                f"{app_id}.domains.canonical",
            )
            if isinstance(entry, dict):
                canonical_map[app_id] = list(entry.values())
            elif isinstance(entry, list):
                canonical_map[app_id] = list(entry)
            else:
                raise AnsibleError(
                    f"Unexpected type for 'domains.canonical' in "
                    f"application '{app_id}': {type(entry).__name__}"
                )
        else:
            canonical_map[app_id] = [_default_domain(app_id)]

    alias_map: dict[str, list[str]] = {}
    for app_id, cfg in apps.items():
        domains_cfg = (cfg or {}).get("domains", {})
        if domains_cfg is None:
            alias_map[app_id] = []
            continue

        default = _default_domain(app_id)

        if isinstance(domains_cfg, dict) and not domains_cfg:
            alias_map[app_id] = [default] if auto_build_alias else []
            continue

        aliases = _parse_entry(domains_cfg, "aliases", app_id) or []
        has_aliases = "aliases" in domains_cfg
        has_canonical = "canonical" in domains_cfg

        if has_aliases:
            if auto_build_alias and default not in aliases:
                aliases.append(default)
        elif has_canonical:
            canon = canonical_map.get(app_id, [])
            if default not in canon and default not in aliases and auto_build_alias:
                aliases.append(default)

        alias_map[app_id] = aliases

    mappings: list[dict[str, str]] = []
    for app_id, sources in alias_map.items():
        canon_list = canonical_map.get(app_id, [])
        target = canon_list[0] if canon_list else _default_domain(app_id)
        for src in sources:
            if src == target:
                continue
            mappings.append({"source": src, "target": target})

    return mappings


class LookupModule(LookupBase):
    """Return CURRENT_PLAY_REDIRECT_DOMAINS as a list of {source,target} dicts.

    A user-supplied mapping may be a wildcard ``*.<zone>`` and may carry
    ``keep_path: false`` to drop the request URI from its 301.

    Merges, in order:
      1. user-supplied ``redirect_domain_mappings`` (if any)
      2. ``{DOMAIN_PRIMARY -> DOMAIN_HOMEPAGE}`` (skipped when equal);
         non-empty result triggers ``sys-stk-front-base`` to auto-load
         ``web-opt-rdr-domains`` so openresty has an SNI match for
         DOMAIN_PRIMARY even when no app claims it. On onion nodes
         (``svc-net-tor`` serving the host with a provisioned
         ``services.tor.node``) the bare node-onion apex is scheduled as an
         additional source targeting the same ``DOMAIN_HOMEPAGE`` when that
         is an onion host or has an onion sibling this node serves, which
         the redirect template sends the apex to; a homepage without one
         gets no onion apex entry, so an onion vhost never redirects to
         clearnet. On an onion node the onion-apex entry requires
         ``web-opt-rdr-domains`` in ``lookup('deployment').deployed`` so
         isolated CI variants do not schedule a redirect whose target is not
         served; the clearnet entry needs it only when the node's
         ``NETWORK_MODE`` does not serve clearnet.
      3. per-app alias-to-canonical mappings from
         ``lookup('applications_current_play')``, gated by ``AUTO_BUILD_ALIASES``.

    Steps 1-2 win over conflicting step-3 entries.
    """

    def _run_lookup(self, name: str, variables: dict[str, Any] | None) -> Any:
        plugin = lookup_loader.get(
            name,
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        )
        if plugin is None:
            return None
        result = plugin.run([], variables=variables)
        return result[0] if result else None

    def _node_onion(self, vars_: Mapping[str, Any]) -> str:
        """Return the node onion address when ``svc-net-tor`` serves this host
        (:func:`utils.networks.reachability.tor_serves_host`) with a provisioned
        ``services.tor.node`` in the ``applications`` override, else ``""``."""
        if not tor_serves_host(vars_):
            return ""
        apps = vars_.get("applications")
        svc_tor = apps.get("svc-net-tor") if isinstance(apps, Mapping) else None
        if not isinstance(svc_tor, Mapping):
            return ""
        services = svc_tor.get("services")
        tor = services.get("tor") if isinstance(services, Mapping) else None
        node = tor.get("node") if isinstance(tor, Mapping) else None
        return self._resolve_str(node).strip()

    def _serves_clearnet(self, vars_: Mapping[str, Any]) -> bool:
        """Whether the node's resolved ``NETWORK_MODE`` includes clearnet.

        Args:
            vars_: host variables carrying ``NETWORK_MODE``, ``group_names``
                and ``groups``.
        """
        try:
            mode = resolve_node_mode(
                self._resolve_str(vars_.get("NETWORK_MODE")),
                tor_provided=tor_serves_host(vars_),
            )
        except ValueError as exc:
            raise AnsibleError(f"current_play_redirect_domains: {exc}") from exc
        return CLEARNET in NODE_MODES[mode]

    def _reachable_on_onion(self, domain: str, vars_: Mapping[str, Any]) -> bool:
        """Whether ``domain`` is an onion host or has an onion sibling this
        node serves.

        Args:
            domain: the redirect target.
            vars_: host variables the ``network_siblings`` lookup reads.
        """
        if network_of(domain) == TOR:
            return True
        plugin = lookup_loader.get(
            "network_siblings",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        )
        siblings = plugin.run([domain], variables=dict(vars_))[0] if plugin else None
        return any(network_of(sibling) == TOR for sibling in siblings or [])

    def _resolve_str(self, value: Any) -> str:
        """Template a possibly Jinja-tagged inventory value through
        ``self._templar`` before string-coercion; bare ``str()`` would
        strip the ``TrustedAsTemplate`` tag on Ansible 2.18+."""
        if value is None:
            return ""
        templar = getattr(self, "_templar", None)
        if templar is not None:
            with contextlib.suppress(Exception):
                value = templar.template(value)
        return str(value)

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[dict[str, str]]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        domain_primary = self._resolve_str(vars_.get("DOMAIN_PRIMARY"))
        domain_homepage = self._resolve_str(vars_.get("DOMAIN_HOMEPAGE"))
        auto_build_aliases = bool(vars_.get("AUTO_BUILD_ALIASES", False))

        user_mappings = vars_.get("redirect_domain_mappings") or []
        if not isinstance(user_mappings, list):
            user_mappings = []

        merged = merge_mapping(
            [],
            [
                {
                    **mapping,
                    "source": self._resolve_str(mapping.get("source")),
                    "target": self._resolve_str(mapping.get("target")),
                }
                for mapping in user_mappings
                if isinstance(mapping, Mapping)
            ],
            "source",
        )

        if domain_primary and domain_homepage:
            node_onion = self._node_onion(vars_)
            allowed = True
            if node_onion:
                deployment = self._run_lookup("deployment", vars_)
                deployed = (
                    list(deployment.get("deployed") or [])
                    if isinstance(deployment, Mapping)
                    else []
                )
                allowed = "web-opt-rdr-domains" in deployed
            primary_redirects = []
            if domain_primary != domain_homepage and (
                allowed or self._serves_clearnet(vars_)
            ):
                primary_redirects.append(
                    {"source": domain_primary, "target": domain_homepage}
                )
            if (
                allowed
                and node_onion
                and node_onion != domain_homepage
                and self._reachable_on_onion(domain_homepage, vars_)
            ):
                primary_redirects.append(
                    {"source": node_onion, "target": domain_homepage}
                )
            merged = merge_mapping(merged, primary_redirects, "source")

        current_play_apps = self._run_lookup("applications_current_play", vars_)
        if isinstance(current_play_apps, Mapping):
            per_app = _per_app_redirect_mappings(
                current_play_apps, domain_primary, auto_build_aliases
            )
            merged = merge_mapping(per_app, merged, "source")

        return [merged]

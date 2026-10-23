from ansible.errors import AnsibleError, AnsibleFilterError

from utils.networks.reachability import TOR, network, network_of
from utils.roles.applications.config import get
from utils.tls_common import resolve_primary_domain_from_app


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _disabled_entity_keys(config):
    """Canonical keys claimed by a disabled service entity via ``services.<entity>.domains``."""
    disabled = set()
    for entity in (config.get("services") or {}).values():
        if not isinstance(entity, dict):
            continue
        keys = entity.get("domains")
        if isinstance(keys, list) and not _as_bool(entity.get("enabled", True)):
            disabled.update(str(k) for k in keys)
    return disabled


class FilterModule:
    """Ansible filter plugin for generating logout domains based on logout feature."""

    def filters(self):
        return {
            "logout_domains": self.logout_domains,
        }

    def logout_domains(
        self, applications, group_names, domains=None, network_name=None
    ):
        """
        Return a list of domains for applications where services.logout.enabled is true.

        :param applications: dict of application configs
        :param group_names: list of application IDs to consider
        :param domains: optional resolved domains map (``lookup('domains')``) whose
            per-app entries already carry every network sibling; preferred over the
            raw canonical config so the logout sweep targets the domains the browser
            is actually served at. When given, the sweep keeps only domains of one
            network (the conductor page's CSP blocks cross-network fetches) and
            drops canonical keys whose serving entity is disabled on this node.
        :param network_name: registry name of the network whose domains the sweep
            keeps; defaults to the network of web-svc-logout's own primary domain.
        :return: flat list of domain strings
        """
        try:
            if (
                network_name is None
                and domains is not None
                and "web-svc-logout" in domains
            ):
                try:
                    network_name = network_of(
                        resolve_primary_domain_from_app(
                            domains, "web-svc-logout", err_prefix="logout_domains"
                        )
                    )
                except AnsibleError:
                    network_name = None

            result = []
            for app_id, config in applications.items():
                if app_id not in group_names:
                    continue

                if not get(applications, app_id, "services.logout.enabled", False):
                    continue

                if domains is not None and app_id in domains:
                    domains_entry = domains.get(app_id, [])
                else:
                    domains_entry = (config.get("domains") or {}).get("canonical", [])

                if isinstance(domains_entry, dict):
                    disabled = _disabled_entity_keys(config)
                    flattened = [
                        v
                        for k, v in domains_entry.items()
                        if str(k) not in disabled
                        and str(k).removesuffix(f"_{network(TOR).label}")
                        not in disabled
                    ]
                elif isinstance(domains_entry, list):
                    flattened = domains_entry
                else:
                    flattened = [domains_entry]

                if network_name is not None:
                    flattened = [
                        d
                        for d in flattened
                        if not isinstance(d, str) or network_of(d) == network_name
                    ]

                result.extend(flattened)
        except Exception as e:
            raise AnsibleFilterError(f"logout_domains filter error: {e}") from e
        return result

from ansible.errors import AnsibleError, AnsibleFilterError

from utils.roles.applications.config import get
from utils.tls_common import is_onion_domain, resolve_primary_domain_from_app


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

    def logout_domains(self, applications, group_names, domains=None):
        """
        Return a list of domains for applications where services.logout.enabled is true.

        :param applications: dict of application configs
        :param group_names: list of application IDs to consider
        :param domains: optional resolved domains map (``lookup('domains')``) whose
            per-app entries already carry any onion mirror; preferred over the raw
            canonical config so the logout sweep targets the domains the browser is
            actually served at (over Tor the clearnet host is unreachable via SOCKS).
            When given, the sweep keeps only domains of web-svc-logout's own family
            (the conductor page's CSP blocks cross-family fetches) and drops
            canonical keys whose serving entity is disabled on this node.
        :return: flat list of domain strings
        """
        try:
            page_family_onion = None
            if domains is not None and "web-svc-logout" in domains:
                try:
                    page_family_onion = is_onion_domain(
                        resolve_primary_domain_from_app(
                            domains, "web-svc-logout", err_prefix="logout_domains"
                        )
                    )
                except AnsibleError:
                    page_family_onion = None

            result = []
            for app_id, config in applications.items():
                if app_id not in group_names:
                    continue

                if not get(applications, app_id, "services.logout.enabled", False):
                    continue

                if domains is not None and app_id in domains:
                    domains_entry = domains.get(app_id, [])
                else:
                    domains_entry = (
                        config.get("server", {}).get("domains", {}).get("canonical", [])
                    )

                # normalize to a list of strings
                if isinstance(domains_entry, dict):
                    disabled = _disabled_entity_keys(config)
                    flattened = [
                        v
                        for k, v in domains_entry.items()
                        if str(k) not in disabled
                        and str(k).removesuffix("_onion") not in disabled
                    ]
                elif isinstance(domains_entry, list):
                    flattened = domains_entry
                else:
                    flattened = [domains_entry]

                if page_family_onion is not None:
                    flattened = [
                        d
                        for d in flattened
                        if not isinstance(d, str)
                        or is_onion_domain(d) == page_family_onion
                    ]

                result.extend(flattened)
        except Exception as e:
            raise AnsibleFilterError(f"logout_domains filter error: {e}") from e
        return result

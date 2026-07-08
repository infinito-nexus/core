from ansible.errors import AnsibleFilterError

from utils.roles.applications.config import get


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
            actually served at (over Tor the clearnet host is unreachable via SOCKS)
        :return: flat list of domain strings
        """
        try:
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
                    flattened = list(domains_entry.values())
                elif isinstance(domains_entry, list):
                    flattened = domains_entry
                else:
                    flattened = [domains_entry]

                result.extend(flattened)
        except Exception as e:
            raise AnsibleFilterError(f"logout_domains filter error: {e}") from e
        return result

from ansible.errors import AnsibleFilterError
from utils.applications.config import get


class FilterModule(object):
    """Ansible filter plugin for generating logout domains based on logout feature."""

    def filters(self):
        return {
            "logout_domains": self.logout_domains,
        }

    def logout_domains(self, applications, group_names):
        """
        Return a list of domains for applications where services.logout.enabled is true.

        :param applications: dict of application configs
        :param group_names: list of application IDs to consider
        :return: flat list of domain strings
        """
        try:
            result = []
            for app_id, config in applications.items():
                if app_id not in group_names:
                    continue

                if not get(applications, app_id, "services.logout.enabled", False):
                    continue

                # use canonical domains list if present
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

            return result

        except Exception as e:
            raise AnsibleFilterError(f"logout_domains filter error: {e}")

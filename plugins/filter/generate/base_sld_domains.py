import re

from ansible.errors import AnsibleFilterError


class FilterModule:
    def filters(self):
        return {"generate_base_sld_domains": self.generate_base_sld_domains}

    def generate_base_sld_domains(self, domains_list):
        """
        Given a list of hostnames, extract the second-level domain (SLD.TLD) for any hostname
        with two or more labels, return single-label hostnames as-is, and reject IPs,
        empty or malformed strings, and non-strings. Deduplicate and sort.
        """
        if not isinstance(domains_list, list):
            raise AnsibleFilterError(
                f"generate_base_sld_domains expected a list, got {type(domains_list).__name__}"
            )

        ip_pattern = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
        results = set()

        for hostname in domains_list:
            if not isinstance(hostname, str):
                raise AnsibleFilterError(
                    f"Invalid domain entry (not a string): {hostname!r}"
                )

            # nocheck: project-root-import  the `".."` below is a substring check, not a path build
            if (
                not hostname
                or hostname.startswith(".")
                or hostname.endswith(".")
                or ".." in hostname  # nocheck: project-root-import
            ):
                raise AnsibleFilterError(
                    f"Invalid domain entry (malformed): {hostname!r}"
                )

            if ip_pattern.match(hostname):
                raise AnsibleFilterError(f"IP addresses not allowed: {hostname!r}")

            labels = hostname.split(".")
            if len(labels) == 1:
                results.add(hostname)
            else:
                sld = ".".join(labels[-2:])
                results.add(sld)

        return sorted(results)

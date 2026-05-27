from ansible.errors import AnsibleFilterError

try:
    import tld
    from tld.exceptions import TldBadUrl, TldDomainNotFound
except ImportError:
    raise AnsibleFilterError(
        "The 'tld' Python package is required for the to_primary_domain filter. Install with 'pip install tld'."
    ) from None


class FilterModule:
    """Custom filter to extract the primary/zone domain from a full domain name"""

    def filters(self):
        return {
            "to_primary_domain": self.to_primary_domain,
        }

    def to_primary_domain(self, domain):
        """
        Converts a full domain or subdomain into its primary/zone domain.
        E.g. 'foo.bar.example.co.uk' -> 'example.co.uk'
        """
        if not isinstance(domain, str):
            raise AnsibleFilterError("Input to to_primary_domain must be a string")
        try:
            res = tld.get_fld(domain, fix_protocol=True)
        except (TldDomainNotFound, TldBadUrl) as exc:
            raise AnsibleFilterError(str(exc)) from exc
        if not res:
            raise AnsibleFilterError(f"Could not extract primary domain from: {domain}")
        return res

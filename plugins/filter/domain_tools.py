# Returns the DNS zone (SLD.TLD) from a hostname.
# Pure-Python, no external deps; handles simple cases. For exotic TLDs use tldextract (see note).
from ansible.errors import AnsibleFilterError


def to_zone(hostname: str) -> str:
    if not isinstance(hostname, str) or not hostname.strip():
        raise AnsibleFilterError("to_zone: hostname must be a non-empty string")
    parts = hostname.strip(".").split(".")
    if len(parts) < 2:
        raise AnsibleFilterError(f"to_zone: '{hostname}' has no TLD part")
    # naive default: last two labels -> SLD.TLD
    return ".".join(parts[-2:])


class FilterModule:
    def filters(self):
        return {
            "to_zone": to_zone,
        }

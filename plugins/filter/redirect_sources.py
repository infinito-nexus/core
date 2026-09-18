from ansible.errors import AnsibleFilterError


def redirect_sources(host: str) -> list[str]:
    """Ordered match prefixes for a redirect that targets ``host``.

    Args:
        host: the upstream host, as it appears in the proxied URL.

    Returns:
        The two host-qualified forms, then the bare ``/`` for a target the
        upstream expressed as an absolute path.
    """
    if not isinstance(host, str) or not host.strip():
        raise AnsibleFilterError("redirect_sources: host must be a non-empty string")
    stripped = host.strip()
    return [
        f"https://{stripped}/",
        f"http://{stripped}/",
        "/",
    ]


class FilterModule:
    def filters(self):
        return {
            "redirect_sources": redirect_sources,
        }

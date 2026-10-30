from __future__ import annotations

# Exception: these service flags mean "this host's agent collects the role's logs", not "the role uses a shared
# service users see". They stay literal booleans without `shared`: a `group_names` expression would be false on a
# host without the provider, which silently drops the opt-in in a multi-host deployment. They have no Playwright surface;
# the provider's own deploy check verifies them.
HOST_AGENT_SERVICES: frozenset[str] = frozenset({"wazuh"})


def is_host_agent_service(service_key: str) -> bool:
    """Return whether a service key is a host-agent flag, exempt from the shared, dynamic-flag and Playwright service-flag lints.

    Args:
        service_key: the top-level key in a role's meta/services.yml.
    """
    return service_key in HOST_AGENT_SERVICES

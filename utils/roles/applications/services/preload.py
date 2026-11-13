from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection


def preloaded(
    service_key: str,
    service_role: str,
    required_ids: Collection[str],
    group_names: Collection[str],
    closure: Collection[str],
) -> bool:
    """Args:
        service_key: the shared service's registry key.
        service_role: the role that provides the service.
        required_ids: the service keys some deployed role requires.
        group_names: the inventory groups of the current host.
        closure: the deployment whitelist's dependency closure, empty without a whitelist.

    Returns:
        whether the service loader preloads the service on this host.
    """
    return (service_key in required_ids or service_role in group_names) and (
        not closure or service_role in closure
    )

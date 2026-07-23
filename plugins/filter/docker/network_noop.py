"""Filter ``docker_network_noop``: classify docker network connect/disconnect errors.

    failed_when: >
      result.rc != 0 and
      not (result.stderr | docker_network_noop('connect'))

Returns True when the stderr of a failed ``docker network connect|disconnect``
only reports an idempotent no-op: the endpoint already is in the desired state
('connect') or the network/container to detach from is absent ('disconnect').
Any other daemon error (permissions, dead daemon, active endpoints) stays False
so the caller's failed_when still trips.
"""

from __future__ import annotations

from ansible.errors import AnsibleFilterError

_NOOP_MARKERS = {
    "connect": (
        "already exists in network",
        "already attached to network",
    ),
    "disconnect": (
        "is not connected",
        "no such network",
        "no such container",
        "not found",
    ),
}


def docker_network_noop(stderr: str | None, operation: str) -> bool:
    markers = _NOOP_MARKERS.get(operation)
    if markers is None:
        raise AnsibleFilterError(
            f"docker_network_noop: unknown operation '{operation}'; "
            f"known: {', '.join(sorted(_NOOP_MARKERS))}"
        )
    text = (stderr or "").lower()
    return any(marker in text for marker in markers)


class FilterModule:
    def filters(self):
        return {"docker_network_noop": docker_network_noop}

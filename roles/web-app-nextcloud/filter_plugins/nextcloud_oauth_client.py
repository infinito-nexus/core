import json

from ansible.errors import AnsibleFilterError

_MARKER = "NC_OAUTH_CLIENT "
_ACTIONS = ("created", "redirect_fixed", "unchanged")


def nextcloud_oauth_client_state(stdout):
    """Read the state files/php/addons/openproject/ensure_nc_client.php prints.

    Args:
      stdout: the helper's stdout; PHP notices may surround its marker line.

    Returns:
      the marker's JSON object (action, id, client_id, removed, and
      client_secret when the client was created) plus ``changed``, true
      unless the client was left as it was and no stale client was removed.

    Raises:
      AnsibleFilterError: when the stdout holds no or several marker lines,
        or an action the helper does not print.
    """
    states = [
        json.loads(line[len(_MARKER) :])
        for line in str(stdout).splitlines()
        if line.startswith(_MARKER)
    ]
    if len(states) != 1:
        raise AnsibleFilterError(
            f"nextcloud_oauth_client_state expects one {_MARKER.strip()} line, got {len(states)}"
        )
    state = states[0]
    if state.get("action") not in _ACTIONS:
        raise AnsibleFilterError(
            f"nextcloud_oauth_client_state: unknown action {state.get('action')!r}"
        )
    state["changed"] = state["action"] != "unchanged" or state.get("removed", 0) > 0
    return state


class FilterModule:
    def filters(self):
        return {"nextcloud_oauth_client_state": nextcloud_oauth_client_state}

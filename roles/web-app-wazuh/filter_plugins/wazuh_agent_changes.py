import base64
import json

from ansible.errors import AnsibleFilterError

AGENT_NOT_FOUND = 1701


def wazuh_agent_changes(agents, key_results):
    """Select the agents whose manager registration differs from the wanted one.

    Args:
        agents: wanted agents, each a dict with ``id``, ``name`` and ``key``.
        key_results: registered loop results of ``GET /agents/{id}/key``, each
            with ``item`` (the agent) and ``stdout`` (the API response body).

    Returns:
        The agents that need a change, each extended with ``action``:
        ``insert`` when the manager has no agent with that id, ``replace``
        when its registered name or key differs. Agents that already match
        are left out, so an empty list means nothing to do.
    """
    responses = {result["item"]["id"]: result["stdout"] for result in key_results}
    changes = []
    for agent in agents:
        agent_id = agent["id"]
        data = json.loads(responses[agent_id]).get("data")
        if data is None:
            raise AnsibleFilterError(f"Wazuh API key lookup for agent {agent_id} failed")
        if not data["affected_items"]:
            codes = {item["error"]["code"] for item in data["failed_items"]}
            if codes != {AGENT_NOT_FOUND}:
                raise AnsibleFilterError(
                    f"Wazuh API key lookup for agent {agent_id} failed with codes {sorted(codes)}"
                )
            changes.append({**agent, "action": "insert"})
            continue
        registered = base64.b64decode(data["affected_items"][0]["key"]).decode()
        if registered != f"{agent_id} {agent['name']} any {agent['key']}":
            changes.append({**agent, "action": "replace"})
    return changes


class FilterModule:
    def filters(self):
        return {"wazuh_agent_changes": wazuh_agent_changes}

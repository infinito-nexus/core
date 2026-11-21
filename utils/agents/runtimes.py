"""Agent runtimes: the roles that declare themselves as one.

A runtime role carries ``agent_runtime`` on the service entry that serves the
runtime, with the ``name`` an agent's ``runtime`` field selects and the
``host`` its agents run on: ``broker`` when the broker spawns one container per
agent from that service's image, ``workspace`` when the agent runs inside the
server workspace. Nothing else lists the runtimes.
"""

from __future__ import annotations

DECLARATION_KEY = "agent_runtime"
HOSTS = ("broker", "workspace")


def declared(applications: dict) -> dict[str, dict]:
    """Return runtime name -> its declaration plus ``application_id`` and
    ``service``, for every service entry that declares ``agent_runtime``.

    Args:
        applications: application id -> its config carrying ``services``.

    Raises:
        ValueError: two service entries declare the same runtime name.
    """
    found: dict[str, dict] = {}
    for application_id, config in sorted((applications or {}).items()):
        services = config.get("services") if isinstance(config, dict) else None
        for service, entry in sorted((services or {}).items()):
            declaration = (
                entry.get(DECLARATION_KEY) if isinstance(entry, dict) else None
            )
            if not isinstance(declaration, dict):
                continue
            name = declaration.get("name")
            if name in found:
                first = found[name]
                raise ValueError(
                    f"agent runtime '{name}' is declared by {first['application_id']}"
                    f" ({first['service']}) and {application_id} ({service})"
                )
            found[name] = {
                **declaration,
                "application_id": application_id,
                "service": service,
            }
    return found


def problems(runtimes: dict[str, dict], named: dict[str, str]) -> list[str]:
    """Return every broken declaration and every runtime an agent names that
    no role declares.

    Args:
        runtimes: the result of ``declared``.
        named: agent role -> the ``runtime`` its ``agent.yml`` names.
    """
    found = [
        f"{entry['application_id']} ({entry['service']}): agent_runtime needs a"
        f" non-empty name and a host of {HOSTS}"
        for name, entry in sorted(runtimes.items(), key=lambda item: str(item[0]))
        if not isinstance(name, str) or not name or entry.get("host") not in HOSTS
    ]
    found.extend(
        f"agents/roles/{role}: runtime '{runtime}' is declared by no role"
        for role, runtime in sorted(named.items())
        if runtime not in runtimes
    )
    return found

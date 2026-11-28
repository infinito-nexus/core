from __future__ import annotations

import json

from provision import inputs, opentofu, remote, sandbox

ZONE_OUTPUTS = ("zone", "zone_id", "status", "name_servers")
ZONE_RESOURCE = "cloudflare_zone.zone"


def reached_field(session, reach, field):
    """Args:
        session: a :class:`Session` opened with ``reach``.
        reach: the ``{path, env}`` entry of ``credentials.json``.
        field: a field of the record at its path.

    Returns:
        The value the session read from that field.
    """
    (name,) = [name for name, source in reach["env"].items() if source == field]
    return session.reached[name]


def state_zone(session):
    """Args:
        session: a :class:`Session` of the zone root.

    Returns:
        The outputs of the zone the state holds, ``{}`` for a state without
        resources.

    Raises:
        FailedError: the state holds resources without every zone output, as
            an interrupted apply leaves it.
    """
    addresses = session.addresses()
    if not addresses:
        return {}
    held = session.outputs()
    missing = sorted(set(ZONE_OUTPUTS) - set(held))
    if missing:
        raise opentofu.FailedError(
            f"{session.key} holds {', '.join(addresses)} without the outputs "
            f"{', '.join(missing)}; an interrupted apply left it, so create and "
            f"show refuse to replace or report it until delete removes it"
        )
    return held


def held_zone(session, domain):
    """Args:
        session: a :class:`Session` of the zone root.
        domain: ``DOMAIN`` of the task.

    Returns:
        The outputs of the zone the state holds, ``{}`` for none.

    Raises:
        RefusedError: the state holds a zone of another name.
    """
    held = state_zone(session)
    if held and held["zone"] != domain:
        raise inputs.RefusedError(
            f"{session.key} holds the zone {held['zone']}, not DOMAIN {domain}; "
            f"delete it before a create of {domain}"
        )
    return held


def zone_api(session, reach):
    return remote.Cloudflare(reach["api"], reached_field(session, reach, "token"))


def zone_unlock(session, _reach, _values, _domain):
    session.unlock()


def state_domain(session):
    """Args:
        session: a :class:`Session` of the zone root whose state holds resources.

    Returns:
        The ``name`` of the zone resource the state holds, read from the state
        itself, so a state an interrupted apply left without outputs names it too.

    Raises:
        FailedError: the state names no zone resource with a name.
    """
    try:
        shown = json.loads(session.run("show", "-json", capture=True))
        resources = shown["values"]["root_module"]["resources"]
        (domain,) = [
            resource["values"]["name"]
            for resource in resources
            if resource["address"] == ZONE_RESOURCE
        ]
    except (ValueError, KeyError, TypeError):
        domain = None
    if not isinstance(domain, str) or not domain:
        raise opentofu.FailedError(
            f"{session.key} names no {ZONE_RESOURCE} with a name, so delete keeps it"
        )
    return domain


def zone_delete(session, _reach, values, _domain):
    if not session.addresses():
        session.forget()
        print(json.dumps({"deleted": True, "zone": None}))
        return
    zone = state_domain(session)
    sandbox.task_write(values.parent, values.name, json.dumps({"domain": zone}))
    session.destroy()
    print(json.dumps({"deleted": True, "zone": zone}))


def zone_show(session, reach, _values, domain):
    held = held_zone(session, domain)
    if not held:
        raise inputs.RefusedError(f"{session.key} holds no zone {domain}")
    live = zone_api(session, reach).zone(held["zone_id"])
    print(json.dumps({"zone": domain, "zone_id": held["zone_id"], **live}))


def zone_create(session, reach, _values, domain):
    held_zone(session, domain)
    cloudflare = zone_api(session, reach)
    account = reached_field(session, reach, "account_id")

    def unclaimed():
        if cloudflare.held(domain, account):
            raise inputs.RefusedError(
                f"the Cloudflare account already holds DOMAIN {domain} "
                f"outside {session.key}"
            )

    outputs = session.apply(unclaimed)
    print(json.dumps({name: outputs[name] for name in ZONE_OUTPUTS}))


ZONE_HANDLERS = {
    "create": zone_create,
    "show": zone_show,
    "delete": zone_delete,
    "unlock": zone_unlock,
}

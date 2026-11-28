from __future__ import annotations

from provision import schema

POLICY_SUFFIX = "-dns"
RECORD_TYPES = frozenset({"A", "AAAA", "CNAME"})
CREATE = "POST"
REPLACE = "PUT"
CHANGE = "PATCH"
READ = "GET"
DELETE = "DELETE"
METHODS = frozenset({CREATE, REPLACE, CHANGE, READ, DELETE})
BODILESS = frozenset({READ, DELETE})
FULL_BODY = frozenset({CREATE, REPLACE})


class ScopeError(Exception):
    """Args:
    message: what the broker refuses, naming the token, the zone or the record.
    """


def _matches(value, rule):
    try:
        schema.check(value, rule)
    except schema.SchemaError:
        return False
    return True


def workspace_of(policies, interface):
    """Args:
        policies: the ``policies`` OpenBao reports on ``auth/token/lookup-self``
            for the token the caller presented.
        interface: the decoded ``interface.json``.

    Returns:
        ``ws-<id>`` of the one policy ``ws-<id>-dns`` the token carries, which
        only the token role ``ws-<id>-dns-child`` grants and only the
        provision roles of that workspace mint through.

    Raises:
        ScopeError: the token carries no policy, more than one, or one that
            names no workspace.
    """
    if not isinstance(policies, list) or len(policies) != 1:
        raise ScopeError(
            f"the token carries {policies!r}, not the one policy ws-<id>{POLICY_SUFFIX}"
        )
    (policy,) = policies
    rule = schema.definition(interface, "workspace")["properties"]["workspace"]
    workspace = policy.removesuffix(POLICY_SUFFIX) if isinstance(policy, str) else ""
    if workspace == policy or not _matches(workspace, rule):
        raise ScopeError(
            f"the token carries {policy!r}, not a policy ws-<id>{POLICY_SUFFIX}"
        )
    return workspace


def owns(name, scope, interface):
    """Args:
        name: a record name as the Cloudflare API carries it.
        scope: ``{"workspace", "zone", "zone_id"}`` of the caller, as for
            :func:`check`.
        interface: the decoded ``interface.json``.

    Returns:
        Whether ``name`` is ``<label>.<workspace>.<zone>`` with one label of
        ``dns_label``, the name the record and server roots write. A name that
        ends in ``<workspace>.<zone>`` without the dot before it, the bare
        ``<workspace>.<zone>``, a deeper name and a name with a trailing dot or
        an upper-case letter are not.
    """
    suffix = f".{scope['workspace']}.{scope['zone']}"
    if not isinstance(name, str) or not name.endswith(suffix):
        return False
    rule = schema.definition(interface, "inputs")["properties"]["dns_label"]
    return _matches(name.removesuffix(suffix), rule)


def _require_name(name, scope, interface):
    if not owns(name, scope, interface):
        raise ScopeError(
            f"{name!r} is no name <label>.{scope['workspace']}.{scope['zone']}"
        )


def _require_type(kind):
    if kind not in RECORD_TYPES:
        raise ScopeError(
            f"the type {kind!r} is none of {', '.join(sorted(RECORD_TYPES))}"
        )


def check(request, scope, existing, interface):
    """Args:
        request: ``{"method", "zone_id", "record_id", "name", "type"}`` of the
            caller's call to ``/zones/<zone_id>/dns_records[/<record_id>]``:
            ``record_id`` empty only for a create; ``name`` and ``type`` those
            of the body, empty for a read and a delete and for a change that
            keeps them. Any other key is ignored.
        scope: ``{"workspace", "zone", "zone_id"}``: the workspace
            :func:`workspace_of` took from the caller's token, and the zone and
            zone id of ``platform/data/provision/dns-scope/<workspace>``, which
            ``workspace apply`` writes; no part of it comes from the request.
        existing: ``{"name", "type"}`` of the record ``record_id`` names, as
            the broker read it with the zone token before forwarding; None for
            a create.
        interface: the decoded ``interface.json``.

    Returns:
        None once the call stays within the caller's own names, so the broker
        forwards it with the zone token.

    Raises:
        ScopeError: the call reaches another zone, a record or a name of
            another workspace, a type no DNS module writes, or an operation
            the broker does not forward; the broker then forwards nothing.
    """
    method = request["method"]
    if method not in METHODS:
        raise ScopeError(f"the broker forwards no {method!r}")
    if not scope["zone_id"] or request["zone_id"] != scope["zone_id"]:
        raise ScopeError(
            f"the zone {request['zone_id']!r} is not the zone of {scope['workspace']}"
        )
    if method == CREATE:
        if request["record_id"] or existing is not None:
            raise ScopeError("a create names no record id")
    elif not request["record_id"] or existing is None:
        raise ScopeError(f"a {method} needs the id of a record the zone holds")
    else:
        _require_name(existing["name"], scope, interface)
        _require_type(existing["type"])
    if method in BODILESS:
        if request["name"] or request["type"]:
            raise ScopeError(f"a {method} carries no record body")
        return
    if method in FULL_BODY or request["name"]:
        _require_name(request["name"], scope, interface)
    if method in FULL_BODY or request["type"]:
        _require_type(request["type"])

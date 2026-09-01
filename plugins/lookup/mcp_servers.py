"""Lookup ``mcp_servers``: which MCP servers this client may connect to.

    {{ lookup('mcp_servers') }}
    -> {"selected": [...], "rejected": [...]}

Discovery is an intersection, not a list. A provider names the clients it
admits in ``allowed_consumers``; a client names the transports and auth
schemes it can present. Only a pair that satisfies both, and whose provider
credential actually resolves, reaches ``selected``.

Everything else lands in ``rejected`` with a stable code:
``consumer_not_allowed``, ``transport_unsupported``, ``auth_unsupported``,
``credential_missing`` and ``endpoint_unreachable``.

``consumer_not_allowed`` is a decision and simply narrows the result.
``transport_unsupported``, ``auth_unsupported`` and ``endpoint_unreachable``
mean the provider did authorize this consumer and the connection still cannot
be rendered, so they abort the run instead of disappearing quietly: a client
that silently ends up with fewer tools than the deployment declared is
indistinguishable from one that works.

Providers are narrowed to ``application_closure(deployment.whitelist)``, the same
set ``sys-service-loader`` preloads from. Inventory membership, ``group_names``
and the raw whitelist all admit roles the run never deploys, and a client then
carries an endpoint nothing is serving. In compose the closure covers everything
present, so only swarm makes the difference visible.

``credential_missing`` is the one authorized rejection that does not abort,
because a provider deploying later in the same play has not written its secret
yet. That exemption ends at the reconciliation stage, which runs once every
provider has: ``assert_authorized_are_renderable(discovery, strict=True)``
treats it as fatal there.

The provider credential is whatever ``mcp.credential`` declares:
``owner`` names the principal, ``source`` where its secret lives
(``token_store`` or the role's own ``credentials``), ``key`` the entry. No
provider inherits the administrator's token.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.manager.credential_key import CREDENTIALS_KEY, SECRETS_KEY
from utils.roles.applications.mcp import DEFAULT_MCP_TRANSPORT, resolve_credential

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REJECT_CONSUMER = "consumer_not_allowed"
REJECT_TRANSPORT = "transport_unsupported"
REJECT_AUTH = "auth_unsupported"
REJECT_CREDENTIAL = "credential_missing"
REJECT_ENDPOINT = "endpoint_unreachable"

FATAL_REJECTIONS = frozenset({REJECT_TRANSPORT, REJECT_AUTH, REJECT_ENDPOINT})

RECONCILE_STRICT_VAR = "MCP_RECONCILE_STRICT"


def endpoint_url(endpoint: Mapping[str, Any]) -> str:
    """Return the URL a client connects to.

    Args:
        endpoint: the discovered endpoint mapping.

    Every discovered endpoint authenticates through a header. A provider that
    keys its session by URL segment instead cannot scope that segment per
    consumer or revoke it, so it is fronted by an adapter and the segment stays
    between the adapter and its upstream.
    """
    return f"http://{endpoint.get('service_key')}:{endpoint.get('port')}{endpoint.get('path')}"


def role_credentials_of(
    applications: Mapping[str, Any], role: str
) -> Mapping[str, Any]:
    """Return a role's own secrets from the merged applications payload.

    Args:
        applications: the merged applications mapping.
        role: the provider's application id.

    They live at ``secrets.credentials``, which is where the roles' own vars
    and every other consumer address them. Reading the top-level
    ``credentials`` instead returns nothing for every provider whose
    ``credential.source`` is ``credentials``, and the deploy then aborts on a
    secret that was provisioned all along.
    """
    return ((applications.get(role) or {}).get(SECRETS_KEY) or {}).get(
        CREDENTIALS_KEY
    ) or {}


def select_deployed(
    servers: list[dict[str, Any]] | None, closure: set[str] | None
) -> list[dict[str, Any]]:
    """Drop providers this run does not deploy.

    An empty or unresolvable closure filters nothing: discovery that silently
    dropped every provider would look exactly like a deployment without any,
    which is the failure this module refuses to produce elsewhere.
    """
    if not servers:
        return list(servers or [])
    if not closure:
        return list(servers)
    return [server for server in servers if server.get("id") in closure]


def build_mcp_discovery(
    servers: Sequence[Mapping[str, Any]] | None,
    consumer_id: str,
    consumer: Mapping[str, Any],
    credentials: Mapping[str, tuple[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    """Return the selected and rejected MCP servers for one client role.

    Args:
        servers: ``roles_with_service('mcp', direction='server')`` entries.
        consumer_id: ``application_id`` of the client doing the discovery.
        consumer: the client's own ``mcp`` block, carrying
            ``supported_transports`` and ``supported_auths``.
        credentials: resolved ``(token, owner)`` per provider role id.
    """
    supported_transports = set(consumer.get("supported_transports") or [])
    supported_auths = set(consumer.get("supported_auths") or [])

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_owners: dict[tuple[str, str], str] = {}

    def reject(server_id: str, code: str, detail: str) -> None:
        rejected.append({"id": server_id, "reason": code, "detail": detail})

    for server in servers or []:
        server_id = str(server.get("id") or "")
        if not server_id or server_id == consumer_id:
            continue

        allowed = list(server.get("allowed_consumers") or [])
        if consumer_id not in allowed:
            reject(
                server_id,
                REJECT_CONSUMER,
                f"{server_id} admits {sorted(allowed)}, not {consumer_id!r}",
            )
            continue

        transport = str(server.get("transport") or DEFAULT_MCP_TRANSPORT)
        if transport not in supported_transports:
            reject(
                server_id,
                REJECT_TRANSPORT,
                f"{server_id} speaks {transport!r}; {consumer_id} speaks "
                f"{sorted(supported_transports)}",
            )
            continue

        auth = str(server.get("auth") or "")
        if auth not in supported_auths:
            reject(
                server_id,
                REJECT_AUTH,
                f"{server_id} authenticates with {auth!r}; {consumer_id} can "
                f"present {sorted(supported_auths)}",
            )
            continue

        token, owner = credentials.get(server_id, ("", ""))
        if not token:
            reject(
                server_id,
                REJECT_CREDENTIAL,
                f"{server_id} declares owner {owner!r} but no secret resolved; "
                f"a provider never borrows the administrator's token",
            )
            continue

        previous = seen_owners.get((owner, token))
        if previous is not None:
            raise AnsibleError(
                f"mcp_servers: {server_id!r} and {previous!r} resolve to the "
                f"same credential owned by {owner!r}. Every provider needs its "
                f"own principal so revoking one cannot disarm the others."
            )
        seen_owners[(owner, token)] = server_id

        endpoint = server.get("endpoint") or {}
        if not endpoint.get("port") or not endpoint.get("path"):
            reject(
                server_id,
                REJECT_ENDPOINT,
                f"{server_id} resolves no reachable endpoint (port or path missing)",
            )
            continue

        selected.append(
            {
                "id": server_id,
                "url": endpoint_url(endpoint),
                "token": token,
                "auth": auth,
                "auth_subject": server.get("auth_subject"),
                "owner": owner,
                "tools": list(server.get("tools") or []),
                "mutating": list(server.get("mutating") or []),
                "transport": transport.replace("_", "-"),
            }
        )

    return {"selected": selected, "rejected": rejected}


def assert_authorized_are_renderable(
    discovery: Mapping[str, Any], strict: bool = False
) -> None:
    """Abort when a provider authorized this consumer but nothing can connect.

    Args:
        discovery: the ``{"selected": ..., "rejected": ...}`` result.
        strict: also treat ``credential_missing`` as fatal. Its exemption buys
            exactly one thing, a provider that deploys later in the same play
            and has not written its secret yet. The reconciliation stage runs
            after every provider, so there the exemption would only hide a
            provider whose credential never resolved at all.
    """
    fatal_reasons = FATAL_REJECTIONS | ({REJECT_CREDENTIAL} if strict else set())
    fatal = [
        entry
        for entry in discovery.get("rejected") or []
        if entry.get("reason") in fatal_reasons
    ]
    if not fatal:
        return
    detail = "; ".join(f"{e['id']}: {e['reason']}: {e['detail']}" for e in fatal)
    raise AnsibleError(
        f"mcp_servers: {len(fatal)} authorized MCP server(s) cannot be "
        f"rendered. {detail}"
    )


def resolve_consumer_id(vars_: Mapping[str, Any], templar: Any) -> str:
    """Return the ``application_id`` of the client performing the discovery.

    Args:
        vars_: the variables in scope for the lookup.
        templar: the templar used to render a deferred ``application_id``.
    """
    raw = vars_.get("application_id")
    if templar is not None and isinstance(raw, str) and "{{" in raw:
        raw = templar.template(raw)
    consumer_id = str(raw or "").strip()
    if not consumer_id:
        raise AnsibleError(
            "mcp_servers: no application_id in scope. Discovery is a "
            "per-consumer intersection, so the calling role must be known."
        )
    return consumer_id


class LookupModule(LookupBase):
    def _deploy_closure(self, templar: Any, vars_: dict[str, Any]) -> set[str]:
        """Roles this run deploys, or an empty set when that cannot be resolved."""
        try:
            whitelist = lookup_loader.get(
                "deployment", loader=self._loader, templar=templar
            ).run([], variables=vars_)[0]["whitelist"]
            return set(
                lookup_loader.get(
                    "application_closure", loader=self._loader, templar=templar
                ).run([whitelist], variables=vars_)[0]
            )
        except (AnsibleError, KeyError, IndexError, TypeError):
            return set()

    def run(
        self,
        terms: Sequence[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError("mcp_servers: expected no terms, lookup('mcp_servers')")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        consumer_id = resolve_consumer_id(vars_, templar)

        servers = lookup_loader.get(
            "roles_with_service", loader=self._loader, templar=templar
        ).run(
            ["mcp"],
            variables=vars_,
            topic="mcp",
            direction="server",
            scope="deployment",
        )[0]

        servers = select_deployed(servers, self._deploy_closure(templar, vars_))

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=vars_)[0]
        users = lookup_loader.get("users", loader=self._loader, templar=templar).run(
            [], variables=vars_
        )[0]

        consumer = (applications.get(consumer_id) or {}).get("mcp") or {}

        credentials: dict[str, tuple[str, str]] = {}
        for server in servers:
            server_id = str(server.get("id") or "")
            role_credentials = role_credentials_of(applications, server_id)
            credentials[server_id] = resolve_credential(server, users, role_credentials)

        discovery = build_mcp_discovery(servers, consumer_id, consumer, credentials)
        assert_authorized_are_renderable(
            discovery, strict=bool(vars_.get(RECONCILE_STRICT_VAR))
        )
        return [discovery]

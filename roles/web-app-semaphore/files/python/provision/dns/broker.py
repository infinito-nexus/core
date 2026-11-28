from __future__ import annotations

import contextlib
import http.server
import json
import re
from pathlib import Path

from provision import admission, remote, session
from provision.dns import scope as dns_scope

FLAVOR = "cloudflare"
BEARER = "Bearer "
JSON = "application/json"
BODY_LIMIT = 65536
TIMEOUT = 30
REFUSED = 403
FAILED = 502
MISSING = 404
FORWARDED = frozenset({dns_scope.CREATE, dns_scope.REPLACE, dns_scope.CHANGE})
FAILURES = (remote.RemoteError, OSError, ValueError, KeyError)
RECORDS = re.compile(
    r"/zones/(?P<zone>[0-9a-f]{32})/dns_records(?:/(?P<record>[0-9a-f]{32}))?"
)


def refusal(status, message):
    """Args:
        status: the HTTP status the broker answers with.
        message: why the broker forwards nothing, never a credential.

    Returns:
        The body of a Cloudflare API error, which the provider reports.
    """
    error = {"code": status, "message": f"dns broker: {message}"}
    document = {"success": False, "errors": [error], "messages": [], "result": None}
    return json.dumps(document).encode("utf-8")


def _distinct_keys(pairs):
    seen = set()
    for key, _ in pairs:
        if key.casefold() in seen:
            raise dns_scope.ScopeError(f"the body names the key {key!r} twice")
        seen.add(key.casefold())
    return dict(pairs)


def requested(method, target, base, body):
    """Args:
        method: the HTTP method of the call.
        target: its request target, path and query.
        base: the API path the broker serves, ``base`` of ``credentials.json``.
        body: the body of the call.

    Returns:
        The ``request`` of :func:`dns_scope.check`: the zone id and record id
        of ``<base>/zones/<zone_id>/dns_records[/<record_id>]``, ``name`` and
        ``type`` of the body of a create or a change, and ``body``, the JSON
        object that check judged, serialized again for Cloudflare, None for a
        read and a delete.

    Raises:
        ScopeError: the call carries a query, names another path, or a
            create or a change carries no JSON object with text fields, an
            empty name or type, or a key twice in any letter case.
    """
    path, _, query = target.partition("?")
    match = (
        RECORDS.fullmatch(path.removeprefix(base)) if path.startswith(base) else None
    )
    if query or match is None:
        raise dns_scope.ScopeError(f"the broker forwards no {method} {path}")
    fields = {}
    if method in FORWARDED:
        try:
            fields = json.loads(body, object_pairs_hook=_distinct_keys)
        except ValueError:
            fields = None
        if not isinstance(fields, dict):
            raise dns_scope.ScopeError(f"the body of the {method} is no JSON object")
    name, kind = (fields.get(key, "") for key in ("name", "type"))
    if not isinstance(name, str) or not isinstance(kind, str):
        raise dns_scope.ScopeError(f"the {method} names no record name and type")
    if "" in (fields.get("name"), fields.get("type")):
        raise dns_scope.ScopeError(f"the {method} names an empty record name or type")
    return {
        "method": method,
        "zone_id": match["zone"],
        "record_id": match["record"] or "",
        "name": name,
        "type": kind,
        "body": json.dumps(fields).encode("utf-8") if method in FORWARDED else None,
    }


def cloudflare_record(status, payload):
    """Args:
        status: the status of the broker's own read of a record.
        payload: its body.

    Returns:
        ``{"name", "type"}`` of the record, the ``existing`` of
        :func:`dns_scope.check`.

    Raises:
        RemoteError: Cloudflare answered no successful record.
    """
    try:
        result = json.loads(payload)["result"] if status == 200 else None
    except (ValueError, KeyError, TypeError):
        result = None
    if not isinstance(result, dict) or not all(
        isinstance(result.get(key), str) for key in ("name", "type")
    ):
        raise remote.RemoteError(f"Cloudflare GET record: HTTP {status}, no record")
    return {"name": result["name"], "type": result["type"]}


class Platform:
    """Args:
    address: the OpenBao origin.
    cafile: a CA bundle that verifies it, empty for the system trust.
    login: the file of the broker's AppRole, ``{"role_id", "secret_id"}``,
        readable by the broker's uid alone.
    reach: the ``cloudflare`` entry of ``credentials.json``.
    """

    def __init__(self, address, cafile, login, reach):
        self.address = address
        self.cafile = cafile
        self.login = Path(login)
        self.reach = reach

    def caller(self, token):
        """Args:
            token: the bearer token of the call.

        Returns:
            The ``policies`` OpenBao reports for it.

        Raises:
            ScopeError: OpenBao refuses the token.
        """
        client = remote.OpenBao(self.address, self.cafile)
        client.token = token
        try:
            return client.policies()
        except remote.RemoteError:
            raise dns_scope.ScopeError("OpenBao refuses the bearer token") from None

    @contextlib.contextmanager
    def opened(self, workspace):
        """Args:
            workspace: ``ws-<id>`` of the caller.

        Returns:
            A context yielding ``(scope, zone token)``: the ``scope`` of
            :func:`dns_scope.check` from the record ``workspace apply`` pins,
            and the token of that zone, both read with a login of the
            broker's AppRole that OpenBao revokes on exit; a revoke OpenBao
            fails leaves that login until the AppRole's ``token_ttl``.
        """
        pair = json.loads(self.login.read_bytes())
        bao = remote.OpenBao(self.address, self.cafile)
        bao.approle(pair["role_id"], pair["secret_id"])
        try:
            broker = self.reach[session.BROKER]
            path = broker["scope"].format(workspace=workspace)
            scope = bao.read(path, ("zone", "zone_id"))
            (field,) = self.reach["env"].values()
            token = bao.read(self.reach["path"].format(zone=scope["zone"]), (field,))
            yield {"workspace": workspace, **scope}, token[field]
        finally:
            with contextlib.suppress(remote.RemoteError):
                bao.revoke()

    def cloudflare(self, method, zone_id, record_id, token, body):
        """Args:
            method: the HTTP method.
            zone_id: the zone of the call.
            record_id: the record of the call, empty for a create.
            token: the zone token.
            body: the body to forward, None for none.

        Returns:
            ``(status, headers, body)`` of Cloudflare's answer.
        """
        api = self.reach[session.BROKER]["api"]
        url = f"{api}/{zone_id}/dns_records"
        url += f"/{record_id}" if record_id else ""
        headers = {"Accept": JSON, "Authorization": f"{BEARER}{token}"}
        if body is not None:
            headers["Content-Type"] = JSON
        return remote.exchange(url, method, headers, body, remote.SYSTEM_TRUST, TIMEOUT)


def answer(request, authorization, platform, interface):
    """Args:
        request: :func:`requested`, whose ``body`` is what Cloudflare receives.
        authorization: the ``Authorization`` header of the call.
        platform: the :class:`Platform` or a stand-in with its methods.
        interface: the decoded ``interface.json``.

    Returns:
        ``(status, headers, body)`` of Cloudflare's answer to the call,
        forwarded with the zone token once :func:`dns_scope.check` admits it,
        or of the broker's own read of a record id the caller's zone does not
        hold.

    Raises:
        ScopeError: the call names no bearer token of a caller policy, or
            :func:`dns_scope.check` refuses it.
    """
    token = authorization.removeprefix(BEARER)
    if not authorization.startswith(BEARER) or not token:
        raise dns_scope.ScopeError("the call names no bearer token")
    workspace = dns_scope.workspace_of(platform.caller(token), interface)
    with platform.opened(workspace) as (scope, zone_token):
        existing = None
        own = bool(scope["zone_id"]) and request["zone_id"] == scope["zone_id"]
        if request["record_id"] and own:
            status, headers, payload = platform.cloudflare(
                dns_scope.READ, scope["zone_id"], request["record_id"], zone_token, None
            )
            if status == MISSING:
                return status, headers, payload
            existing = cloudflare_record(status, payload)
        dns_scope.check(request, scope, existing, interface)
        return platform.cloudflare(
            request["method"],
            request["zone_id"],
            request["record_id"],
            zone_token,
            request["body"],
        )


class Handler(http.server.BaseHTTPRequestHandler):
    timeout = TIMEOUT

    def read_body(self) -> bytes:
        """
        Returns:
            The request body.

        Raises:
            dns_scope.ScopeError: the body is longer than BODY_LIMIT or its
                length negative.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= BODY_LIMIT:
            raise dns_scope.ScopeError(f"a body of {length} bytes")
        return self.rfile.read(length)

    def forward(self):
        try:
            body = self.read_body()
            request = requested(self.command, self.path, self.server.base, body)
            status, headers, payload = answer(
                request,
                self.headers.get("Authorization", ""),
                self.server.platform,
                self.server.interface,
            )
            kind = headers.get("content-type", JSON)
        except dns_scope.ScopeError as refused:
            self.log_message("refused %s: %s", self.command, refused)
            status, kind, payload = REFUSED, JSON, refusal(REFUSED, str(refused))
        except FAILURES as failure:
            reason = str(failure) if isinstance(failure, remote.RemoteError) else ""
            self.log_message("failed %s: %s", self.command, reason or type(failure))
            status, kind, payload = FAILED, JSON, refusal(FAILED, reason or "failed")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def do_PUT(self):
        self.forward()

    def do_PATCH(self):
        self.forward()

    def do_DELETE(self):
        self.forward()


class Server(http.server.ThreadingHTTPServer):
    """Args:
    address: ``(host, port)`` the broker listens on.
    platform: the :class:`Platform`.
    interface: the decoded ``interface.json``.
    base: the API path the broker serves.
    """

    def __init__(self, address, platform, interface, base):
        super().__init__(address, Handler)
        self.platform = platform
        self.interface = interface
        self.base = base


def serve(login, address, cafile):
    """Args:
        login: the file of the broker's AppRole.
        address: the OpenBao origin.
        cafile: a CA bundle that verifies it, empty for the system trust.

    Returns:
        Never while it serves the DNS broker on the loopback address of the
        ``broker`` of ``credentials.json``, which the provision runner's
        sandboxes share and nothing outside the container reaches.
    """
    reach = admission.credentials()["dns"][FLAVOR]
    interface = json.loads((session.OPENTOFU / "interface.json").read_bytes())
    broker = reach[session.BROKER]
    platform = Platform(address, cafile, login, reach)
    listen = (broker["listen"], broker["port"])
    Server(listen, platform, interface, broker["base"]).serve_forever()

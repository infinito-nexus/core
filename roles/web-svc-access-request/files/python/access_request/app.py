"""The access-request web service: request form, review page and grant.

Config: ``ACCESS_REQUEST_CONFIG`` names the JSON file the deploy renders;
``ACCESS_REQUEST_SMTP_PASSWORD`` and ``ACCESS_REQUEST_ZAMMAD_TOKEN`` carry the
two secrets, ``ACCESS_REQUEST_DATABASE`` the SQLite file.
"""

from __future__ import annotations

import html
import json
import logging
import os
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import approvers, delivery, identity, keycloak, store
from .i18n import Messages

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

LOG = logging.getLogger("access_request")
MAIL_LABELS = (
    "form_application",
    "form_roles",
    "form_reason",
    "review_requester",
    "review_title",
    "review_console",
)


class Service:
    """The WSGI application.

    Args:
        config: the rendered service configuration.
        requests: the request store.
        mail: the SMTP relay.
        zammad: the ticket API.
        realm: the Keycloak realm.
    """

    def __init__(
        self,
        config: dict[str, Any],
        requests: store.Store,
        mail: delivery.Mail,
        zammad: delivery.Zammad,
        realm: keycloak.Realm,
    ) -> None:
        self.config = config
        self.store = requests
        self.mail = mail
        self.zammad = zammad
        self.realm = realm

    def __call__(
        self, environ: dict[str, Any], start_response: Callable
    ) -> Iterable[bytes]:
        headers = {
            key[5:].replace("_", "-"): value
            for key, value in environ.items()
            if key.startswith("HTTP_")
        }
        messages = Messages(
            self.config["i18n"],
            self.config["rbac_i18n"],
            headers.get("ACCEPT-LANGUAGE", ""),
        )
        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET")
        if path == "/healthz":
            return self._respond(start_response, "200 OK", "ok", "text/plain")
        try:
            person = identity.session_person(headers)
        except identity.IdentityError:
            return self._signin_page(start_response, messages)
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        if path == "/" and method == "GET":
            return self._form(start_response, messages, query)
        if path == "/" and method == "POST":
            return self._submit(start_response, messages, person, self._fields(environ))
        if path.startswith("/review/"):
            request_id = path.removeprefix("/review/").strip("/")
            token = identity.session_token(headers)
            try:
                if method == "POST":
                    return self._decide(
                        start_response,
                        messages,
                        person,
                        token,
                        request_id,
                        self._fields(environ),
                    )
                return self._review(
                    start_response, messages, person, token, request_id, ""
                )
            except keycloak.GrantError as error:
                if error.status == 401:
                    return self._signin_page(start_response, messages)
                raise
        return self._page(
            start_response, "404 Not Found", messages, messages("form_title"), ""
        )

    @staticmethod
    def _fields(environ: dict[str, Any]) -> dict[str, list[str]]:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length).decode("utf-8") if length else ""
        return urllib.parse.parse_qs(body, keep_blank_values=True)

    @staticmethod
    def _respond(start_response, status: str, body: str, kind: str) -> list[bytes]:
        data = body.encode("utf-8")
        start_response(
            status,
            [
                ("Content-Type", f"{kind}; charset=utf-8"),
                ("Content-Length", str(len(data))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [data]

    def _document(
        self,
        start_response,
        status: str,
        messages: Messages,
        title: str,
        header: str,
        body: str,
    ) -> list[bytes]:
        document = (
            f'<!DOCTYPE html><html lang="{html.escape(messages.code)}" dir="{html.escape(messages.direction)}">'
            f'<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title></head>"
            f'<body>{header}<main class="container py-4" id="access-request"><h1>{html.escape(title)}</h1>{body}</main></body></html>'
        )
        return self._respond(start_response, status, document, "text/html")

    def _page(
        self, start_response, status: str, messages: Messages, title: str, body: str
    ) -> list[bytes]:
        return self._document(
            start_response, status, messages, title, self._signout(messages), body
        )

    def _signin_page(self, start_response, messages: Messages) -> list[bytes]:
        return self._document(
            start_response,
            "401 Unauthorized",
            messages,
            messages("signin_title"),
            "",
            self._signin(messages),
        )

    @staticmethod
    def _signin(messages: Messages) -> str:
        return (
            f'<p id="signin-text">{html.escape(messages("signin_text"))}</p>'
            f'<a class="btn btn-primary" id="signin" href="/oauth2/sign_out?rd=%2F">{html.escape(messages("signin_action"))}</a>'
        )

    def _signout(self, messages: Messages) -> str:
        return (
            '<header class="container d-flex justify-content-end pt-3" id="session">'
            f'<a class="btn btn-outline-secondary btn-sm" id="signout" href="{html.escape(self.config["signout_url"])}">{html.escape(messages("signout_action"))}</a>'
            "</header>"
        )

    def _entry(self, application: str) -> dict[str, Any] | None:
        return self.config["catalogue"].get(application)

    def _form(
        self,
        start_response,
        messages: Messages,
        query: dict[str, list[str]],
        notice: str = "",
    ) -> list[bytes]:
        application = (query.get("application") or [""])[0]
        entry = self._entry(application)
        title = messages("form_title")
        if entry is None:
            return self._page(
                start_response,
                "404 Not Found",
                messages,
                title,
                f'<p id="unknown">{html.escape(messages("form_unknown_application"))}</p>',
            )
        wanted = set(query.get("role") or []) or {entry["default"]}
        options = []
        for role in entry["roles"]:
            badge = (
                f' <span class="badge text-bg-warning" data-administrator="true">{html.escape(messages("form_administrator"))}</span>'
                if role["administrator"]
                else ""
            )
            checked = " checked" if role["id"] in wanted else ""
            options.append(
                '<div class="form-check">'
                f'<input class="form-check-input" type="checkbox" name="roles" id="role-{html.escape(role["id"])}" value="{html.escape(role["id"])}"{checked}>'
                f'<label class="form-check-label" for="role-{html.escape(role["id"])}"><strong>{html.escape(role["id"])}</strong>{badge}'
                f' <span class="text-muted">{html.escape(messages.role(application, role["role"], role["description"]))}</span></label></div>'
            )
        body = (
            f"{notice}"
            f'<form method="post" action="/" id="request-form">'
            f'<input type="hidden" name="application" value="{html.escape(application)}">'
            f'<p><strong>{html.escape(messages("form_application"))}:</strong> <span id="application">{html.escape(application)}</span></p>'
            f"<fieldset><legend>{html.escape(messages('form_roles'))}</legend>{''.join(options)}</fieldset>"
            f'<label class="form-label" for="reason">{html.escape(messages("form_reason"))}</label>'
            f'<textarea class="form-control" id="reason" name="reason" required></textarea>'
            f'<button class="btn btn-primary mt-3" type="submit" id="submit">{html.escape(messages("form_submit"))}</button>'
            "</form>"
        )
        return self._page(start_response, "200 OK", messages, title, body)

    def _alert(self, text: str, kind: str, element: str) -> str:
        return (
            f'<div class="alert alert-{kind}" id="{element}">{html.escape(text)}</div>'
        )

    def _submit(
        self,
        start_response,
        messages: Messages,
        person: store.Person,
        fields: dict[str, list[str]],
    ) -> list[bytes]:
        form = identity.request_form(fields)
        entry = self._entry(form["application"])
        query = {"application": [form["application"]], "role": form["roles"]}
        if entry is None:
            return self._form(start_response, messages, query)
        known = {r["id"] for r in entry["roles"]}
        roles = [r for r in form["roles"] if r in known]
        try:
            request_id, created = self.store.submit(
                person, form["application"], roles, form["reason"]
            )
        except store.RequestError:
            return self._form(
                start_response,
                messages,
                query,
                self._alert(messages("form_reason_required"), "danger", "invalid"),
            )
        self._notify_approvers(
            messages,
            person,
            form["application"],
            entry,
            roles,
            form["reason"],
            request_id,
        )
        notice = messages("form_created") if created else messages("form_updated")
        link = f'<p><a id="review" href="{html.escape(self._review_url(request_id))}">{html.escape(messages("review_title"))}</a></p>'
        return self._page(
            start_response,
            "200 OK",
            messages,
            messages("form_title"),
            self._alert(notice, "success", "created" if created else "updated") + link,
        )

    def _review_url(self, request_id: str) -> str:
        return f"{self.config['public_url'].rstrip('/')}/review/{request_id}"

    def _notify_approvers(
        self, messages, person, application, entry, roles, reason, request_id
    ) -> None:
        selected = [r for r in entry["roles"] if r["id"] in roles]
        text = delivery.request_text(
            requester=person.username,
            email=person.email,
            application=application,
            roles=selected,
            reason=reason,
            review_url=self._review_url(request_id),
            console_url=self.realm.user_groups_console(person.sub),
            labels={key: messages(key) for key in MAIL_LABELS},
        )
        subject = messages(
            "mail_request_subject", application=application, requester=person.username
        )
        try:
            self.mail.send(self.config["approver_emails"], subject, text)
        except delivery.DeliveryError:
            LOG.exception("approver mail for request %s failed", request_id)
        if self.zammad.enabled:
            try:
                self.zammad.ticket(person.email, subject, text)
            except delivery.DeliveryError:
                LOG.exception("zammad ticket for request %s failed", request_id)

    def _review(
        self, start_response, messages, person, token, request_id, notice
    ) -> list[bytes]:
        request = self.store.get(request_id)
        title = messages("review_title")
        if request is None:
            return self._page(start_response, "404 Not Found", messages, title, "")
        entry = self._entry(request["application"]) or {"roles": []}
        allowed = approvers.grantable(
            person, entry["roles"], request["roles"], self.config["platform_group"]
        )
        current = keycloak.user_groups(self.realm, token, request["requester_sub"])
        requested = [r for r in entry["roles"] if r["id"] in request["roles"]]
        rows = []
        for role in requested:
            disabled = (
                ""
                if role["id"] in allowed and request["status"] == store.OPEN
                else " disabled"
            )
            held = role["path"] in current
            rows.append(
                f'<tr data-role="{html.escape(role["id"])}"><td><input class="form-check-input" type="checkbox" name="roles" value="{html.escape(role["id"])}" id="grant-{html.escape(role["id"])}" checked{disabled}></td>'
                f'<td><label for="grant-{html.escape(role["id"])}">{html.escape(role["id"])}</label></td><td><code>{html.escape(role["path"])}</code></td>'
                f"<td>{html.escape(messages.role(request['application'], role['role'], role['description']))}</td>"
                f'<td class="diff">{"=" if held else "+"}</td></tr>'
            )
        groups = "".join(f"<li><code>{html.escape(g)}</code></li>" for g in current)
        body = (
            f"{notice}"
            f'<p><strong>{html.escape(messages("review_requester"))}:</strong> <span id="requester">{html.escape(request["requester_username"])}</span> &lt;{html.escape(request["requester_email"])}&gt;</p>'
            f'<p><strong>{html.escape(messages("form_application"))}:</strong> <span id="application">{html.escape(request["application"])}</span></p>'
            f'<p><strong>{html.escape(messages("form_reason"))}:</strong></p><blockquote id="reason">{html.escape(request["reason"])}</blockquote>'
            f'<form method="post" id="review-form"><table class="table"><thead><tr><th></th><th>{html.escape(messages("form_roles"))}</th><th></th><th></th>'
            f"<th>{html.escape(messages('review_added_groups'))}</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
            f'<button class="btn btn-primary" type="submit" name="action" value="confirm" id="confirm">{html.escape(messages("review_confirm"))}</button> '
            f'<button class="btn btn-outline-danger" type="submit" name="action" value="reject" id="reject">{html.escape(messages("review_reject"))}</button></form>'
            f'<h2>{html.escape(messages("review_current_groups"))}</h2><ul id="current-groups">{groups}</ul>'
            f'<p><a id="console" href="{html.escape(self.realm.user_groups_console(request["requester_sub"]))}">{html.escape(messages("review_console"))}</a></p>'
        )
        return self._page(start_response, "200 OK", messages, title, body)

    def _decide(
        self, start_response, messages, person, token, request_id, fields
    ) -> list[bytes]:
        request = self.store.get(request_id)
        if request is None:
            return self._page(
                start_response, "404 Not Found", messages, messages("review_title"), ""
            )
        entry = self._entry(request["application"]) or {"roles": []}
        allowed = approvers.grantable(
            person, entry["roles"], request["roles"], self.config["platform_group"]
        )
        if not allowed:
            return self._review(
                start_response,
                messages,
                person,
                token,
                request_id,
                self._alert(messages("review_not_allowed"), "danger", "not-allowed"),
            )
        if (fields.get("action") or [""])[0] == "reject":
            self._close(messages, request, [])
            return self._review(
                start_response,
                messages,
                person,
                token,
                request_id,
                self._alert(messages("review_rejected"), "info", "rejected"),
            )
        selected = [r for r in fields.get("roles") or [] if r in allowed]
        try:
            decision = self.store.approve(
                request_id, person, selected, four_eyes=bool(self.config["four_eyes"])
            )
        except store.RequestError:
            return self._review(
                start_response,
                messages,
                person,
                token,
                request_id,
                self._alert(
                    messages("review_same_approver"), "warning", "same-approver"
                ),
            )
        if not decision.grant:
            return self._review(
                start_response,
                messages,
                person,
                token,
                request_id,
                self._alert(messages("review_waiting_second"), "info", "waiting"),
            )
        paths = {r["id"]: r["path"] for r in entry["roles"]}
        accepted = keycloak.grant(
            self.realm,
            token,
            request["requester_sub"],
            [paths[r] for r in decision.roles],
        )
        granted = [r for r in decision.roles if paths[r] in accepted]
        self._close(messages, request, granted)
        return self._review(
            start_response,
            messages,
            person,
            token,
            request_id,
            self._alert(messages("review_granted"), "success", "granted"),
        )

    def _close(self, messages, request, granted: list[str]) -> None:
        status = self.store.close(request["id"], granted)
        subject = messages(f"mail_{status}_subject", application=request["application"])
        body = "\n".join([subject, "", *granted])
        try:
            self.mail.send([request["requester_email"]], subject, body)
        except delivery.DeliveryError:
            LOG.exception("requester mail for request %s failed", request["id"])


def from_environment() -> Service:
    """Build the service from the rendered config and the environment."""
    env = os.environ
    with Path(env["ACCESS_REQUEST_CONFIG"]).open(encoding="utf-8") as handle:
        config = json.load(handle)
    smtp = config["mail"]
    return Service(
        config,
        store.Store(env["ACCESS_REQUEST_DATABASE"]),
        delivery.Mail(
            host=smtp["host"],
            port=int(smtp["port"]),
            tls=bool(smtp["tls"]),
            start_tls=bool(smtp["start_tls"]),
            auth=bool(smtp["auth"]),
            username=smtp["username"],
            password=env["ACCESS_REQUEST_SMTP_PASSWORD"],
            sender=smtp["from"],
            ca_file=config["ca_file"],
        ),
        delivery.Zammad(
            url=config["zammad"]["url"],
            token=env["ACCESS_REQUEST_ZAMMAD_TOKEN"],
            group=config["zammad"]["group"],
            ca_file=config["ca_file"],
        ),
        keycloak.Realm(
            base_url=config["realm"]["base_url"],
            realm=config["realm"]["realm"],
            console_url=config["realm"]["console_url"],
            ca_file=config["ca_file"],
        ),
    )

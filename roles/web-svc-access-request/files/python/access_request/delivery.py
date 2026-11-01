"""Telling approvers and requesters: mail through the platform relay, tickets in Zammad."""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


class DeliveryError(Exception):
    """A mail or a ticket could not be delivered."""


@dataclass(frozen=True)
class Mail:
    """The SMTP relay, as ``lookup('email', application_id)`` resolved it.

    Args:
        host: relay host.
        port: relay port.
        tls: implicit TLS.
        start_tls: STARTTLS after connecting.
        auth: whether to log in.
        username: login.
        password: password.
        sender: the From address.
        ca_file: CA bundle to trust, empty for the system store.
    """

    host: str
    port: int
    tls: bool
    start_tls: bool
    auth: bool
    username: str
    password: str
    sender: str
    ca_file: str

    def send(self, recipients: list[str], subject: str, body: str) -> None:
        """Send one plain-text mail.

        Args:
            recipients: To addresses; an empty list sends nothing.
            subject: subject line.
            body: text body.
        """
        recipients = [r for r in recipients if r]
        if not recipients:
            return
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context(cafile=self.ca_file or None)
        try:
            if self.tls:
                client = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=30, context=context
                )
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=30)
            with client:
                if self.start_tls and not self.tls:
                    client.starttls(context=context)
                if self.auth:
                    client.login(self.username, self.password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise DeliveryError(f"mail to {recipients}: {error}") from error


@dataclass(frozen=True)
class Zammad:
    """The Zammad ticket API, when ``web-app-zammad`` is deployed.

    Args:
        url: Zammad base URL; empty disables tickets.
        token: API token of the agent the service files tickets as.
        group: the Zammad group the tickets land in.
        ca_file: CA bundle to trust, empty for the system store.
    """

    url: str
    token: str
    group: str
    ca_file: str

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def ticket(self, customer_email: str, title: str, body: str) -> dict[str, Any]:
        """Open a ticket for the requester and return Zammad's answer.

        Args:
            customer_email: the requester; ``guess:`` lets Zammad find or create them.
            title: ticket title.
            body: the first article.
        """
        payload = {
            "title": title,
            "group": self.group,
            "customer_id": f"guess:{customer_email}",
            "article": {
                "subject": title,
                "body": body,
                "type": "note",
                "internal": False,
                "content_type": "text/plain",
            },
        }
        request = urllib.request.Request(  # noqa: S310 - self.url is the deploy-time Zammad URL
            f"{self.url.rstrip('/')}/api/v1/tickets",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Token token={self.token}",
                "Content-Type": "application/json",
            },
        )
        context = ssl.create_default_context(cafile=self.ca_file or None)
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as answer:  # noqa: S310 - see above
                return json.loads(answer.read() or b"{}")
        except (urllib.error.URLError, ValueError) as error:
            raise DeliveryError(f"zammad ticket: {error}") from error


def request_text(
    *,
    requester: str,
    email: str,
    application: str,
    roles: list[dict[str, str]],
    reason: str,
    review_url: str,
    console_url: str,
    labels: dict[str, str],
) -> str:
    """Return the text a ticket and an approver mail carry.

    Args:
        requester: username of the requester.
        email: their address.
        application: application id.
        roles: ``{id, path, description}`` of every requested role.
        reason: the requester's reason.
        review_url: the review page of the request.
        console_url: the requester's groups in the Keycloak admin console.
        labels: the catalog texts for ``form_application``, ``form_roles``,
            ``form_reason``, ``review_requester``, ``review_title`` and
            ``review_console``.
    """
    lines = [
        f"{labels['review_requester']}: {requester} <{email}>",
        f"{labels['form_application']}: {application}",
        f"{labels['form_roles']}:",
        *(f"  - {r['id']} ({r['path']}): {r['description']}" for r in roles),
        f"{labels['form_reason']}:",
        reason,
        "",
        f"{labels['review_title']}: {review_url}",
        f"{labels['review_console']}: {console_url}",
    ]
    return "\n".join(lines)

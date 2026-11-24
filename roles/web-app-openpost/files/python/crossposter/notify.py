from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True)
class Mail:
    host: str
    port: int
    security: str
    user: str
    password: str
    sender: str


def report(rows: list[dict]) -> str:
    blocks = [
        "\n".join(
            (
                f"Route:      {row['route']}",
                f"Source:     {row['source_url']}",
                f"Target:     {row['network']} {row['target']}",
                f"State:      {row['state']} after {row['attempts']} attempt(s)",
                f"Last error: {row['last_error']}",
            )
        )
        for row in rows
    ]
    return (
        "The OpenPost crossposter could not deliver these posts:\n\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def message(sender: str, recipients: tuple[str, ...], rows: list[dict]) -> EmailMessage:
    mail = EmailMessage()
    mail["From"] = sender
    mail["To"] = ", ".join(recipients)
    mail["Subject"] = f"OpenPost crossposter: {len(rows)} post(s) need attention"
    mail.set_content(report(rows))
    return mail


def send(mail: Mail, recipients: tuple[str, ...], rows: list[dict]) -> None:
    context = ssl.create_default_context()
    if mail.security == "tls":
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            mail.host, mail.port, context=context, timeout=60
        )
    else:
        client = smtplib.SMTP(mail.host, mail.port, timeout=60)
    with client:
        if mail.security == "starttls":
            client.starttls(context=context)
        if mail.user:
            client.login(mail.user, mail.password)
        client.send_message(message(mail.sender, recipients, rows))

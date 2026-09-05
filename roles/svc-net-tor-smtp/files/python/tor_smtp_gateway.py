#!/usr/bin/env python3
"""SMTP-to-Tor gateway: accept a message, deliver it to the recipient's ``.onion``.

The active mail provider (Stalwart) cannot open a SOCKS connection of its own
(stalwartlabs/stalwart#644), and a ``.onion`` recipient can be reached no other
way — it has no DNS entry, so MX resolution and a direct TCP connect both fail.
So the provider's outbound routing hands every ``.onion`` recipient to this
gateway as a plain SMTP relay target, and the gateway dials
``<recipient-domain>:25`` through Tor's SOCKS5 listener. ``proxy_rdns`` is on:
the hostname is resolved by Tor, never locally, which is the whole point.

Only ``.onion`` recipients are accepted — the gateway is not an open relay and
never touches clearnet delivery, which stays on the provider's normal MX path.

Environment (compose supplies the first four from the role config; the last two
carry operational defaults):
  TOR_SMTP_LISTEN_PORT   bind port (required)
  TOR_SOCKS_HOST         Tor SOCKS host (required)
  TOR_SOCKS_PORT         Tor SOCKS port (required)
  TOR_SMTP_HELO          EHLO name announced to the peer (required — the node's
                         mail identity; never the bind address, which strict
                         receivers reject)
  TOR_SMTP_LISTEN_HOST   bind address (default 0.0.0.0)
  TOR_SMTP_TIMEOUT       per-hop seconds (default 120)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import smtplib

import socks
from aiosmtpd.controller import Controller

log = logging.getLogger("tor-smtp-gateway")

ONION_SMTP_PORT = 25

LISTEN_HOST = os.environ.get("TOR_SMTP_LISTEN_HOST", "0.0.0.0")  # noqa: S104 - relay bind; reachability is gated by the compose network, not this bind
LISTEN_PORT = int(os.environ["TOR_SMTP_LISTEN_PORT"])
SOCKS_HOST = os.environ["TOR_SOCKS_HOST"]
SOCKS_PORT = int(os.environ["TOR_SOCKS_PORT"])
HELO_NAME = os.environ["TOR_SMTP_HELO"]
TIMEOUT = int(os.environ.get("TOR_SMTP_TIMEOUT", "120"))


class _SocksSMTP(smtplib.SMTP):
    """An ``smtplib.SMTP`` whose socket is a Tor SOCKS5 tunnel to a ``.onion``."""

    def __init__(self, onion: str, port: int, timeout: int) -> None:
        self._onion = onion
        self._onion_port = port
        super().__init__(local_hostname=HELO_NAME, timeout=timeout)

    def _get_socket(self, host, port, timeout):
        return socks.create_connection(
            (self._onion, self._onion_port),
            timeout=timeout,
            proxy_type=socks.SOCKS5,
            proxy_addr=SOCKS_HOST,
            proxy_port=SOCKS_PORT,
            proxy_rdns=True,
        )


def _deliver(onion: str, mail_from: str, rcpts: list[str], content: bytes) -> None:
    smtp = _SocksSMTP(onion, ONION_SMTP_PORT, TIMEOUT)
    try:
        smtp.connect(onion, ONION_SMTP_PORT)
        smtp.ehlo_or_helo_if_needed()
        smtp.sendmail(mail_from, rcpts, content)
    finally:
        try:
            smtp.quit()
        except Exception:
            smtp.close()


def _group_by_domain(rcpts: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for rcpt in rcpts:
        domain = rcpt.rsplit("@", 1)[-1].lower()
        grouped.setdefault(domain, []).append(rcpt)
    return grouped


class OnionRelay:
    """aiosmtpd handler that relays each recipient's message over Tor."""

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):  # noqa: N802 - aiosmtpd hook name
        if not address.rsplit("@", 1)[-1].lower().endswith(".onion"):
            return "550 5.7.1 tor-smtp-gateway relays .onion recipients only"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - aiosmtpd hook name
        loop = asyncio.get_running_loop()
        for domain, rcpts in _group_by_domain(envelope.rcpt_tos).items():
            try:
                await loop.run_in_executor(
                    None, _deliver, domain, envelope.mail_from, rcpts, envelope.content
                )
            except Exception as exc:
                log.warning("onion relay to %s failed: %s", domain, exc)
                return f"451 4.4.1 onion relay to {domain} failed"
        return "250 2.0.0 accepted for onion delivery"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    controller = Controller(OnionRelay(), hostname=LISTEN_HOST, port=LISTEN_PORT)
    controller.start()
    log.info(
        "tor-smtp-gateway listening on %s:%s → SOCKS %s:%s",
        LISTEN_HOST,
        LISTEN_PORT,
        SOCKS_HOST,
        SOCKS_PORT,
    )
    stop = asyncio.Event()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        loop.run_until_complete(stop.wait())
    finally:
        controller.stop()
        loop.close()


if __name__ == "__main__":
    main()

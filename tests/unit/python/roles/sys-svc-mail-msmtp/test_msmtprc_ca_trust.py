"""Which CA msmtp is told to trust, per render context.

The rendered file is read inside a container while the template is rendered on
the Ansible target, so naming a host-resolved bundle path measured the wrong
machine. Only two answers are correct: the CA file the compose override mounts
into every service of a self-signed app, or nothing at all - msmtp then falls
back to its own ``system`` default, which ``with-ca-trust.sh`` curates.

The conditions are Jinja and compile with a plain environment plus a ``bool``
filter shim, since ``bool`` is an Ansible filter.
"""

from __future__ import annotations

import re
import unittest
from typing import Any, ClassVar

from jinja2 import Environment, StrictUndefined

from utils.cache.files import read_text

from . import PROJECT_ROOT

TEMPLATE = (
    PROJECT_ROOT / "roles" / "sys-svc-mail-msmtp" / "templates" / "msmtprc.conf.j2"
)
CA_CONTAINER = "/tmp/infinito/ca/root-ca.crt"  # nocheck: S108 - CA_TRUST.inject_cert_container, a container path
EMAIL = {
    "timeout": 30,
    "auth_mechanism": "PLAIN",
    "start_tls": True,
    "tls": True,
    "host": "mail.infinito.example",
    "port": 587,
    "from": "no-reply@infinito.example",
    "auth": False,
}


def _env() -> Environment:
    env = Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - a config file, and Ansible's templar does not escape either
    )
    env.filters["bool"] = bool
    env.filters["on_off"] = lambda value: "on" if value else "off"
    env.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
        pattern, repl, str(value)
    )
    return env


def _render(
    *, in_container: bool, ca_injected: bool, email=None, smtp_host=None, **extra
) -> str:
    """Render msmtprc.

    Args:
        in_container: whether the rendered file is mounted into a container.
        ca_injected: what the ca_injected lookup reports.
        email: the email mapping the lookup returns.
        smtp_host: the host smtp_host resolves to. Defaults to the configured
            relay, which is what the resolver returns outside the rig; pass
            loopback to exercise the in-rig path.
    """
    email_config = email if email is not None else EMAIL

    def lookup(kind, *args, **kwargs):
        if kind == "email":
            return email_config
        if kind == "smtp_host":
            return smtp_host if smtp_host is not None else email_config["host"]
        if kind == "ca_injected":
            return ca_injected
        if kind == "tor_socks_proxy":
            return "socks5h://tor:9050"
        if kind == "tor_socks":
            return "127.0.0.1:9050"
        raise AssertionError(f"unexpected lookup: {kind}")

    template = _env().from_string(read_text(str(TEMPLATE)))
    return template.render(
        lookup=lookup,
        sys_svc_mail_msmtp_in_container=in_container,
        MODE_DEBUG=False,
        CA_TRUST={"inject_cert_container": CA_CONTAINER},
        DOMAIN_PRIMARY="infinito.example",
        **extra,
    )


def _trust_line(rendered: str) -> str | None:
    for line in rendered.splitlines():
        if line.startswith("tls_trust_file"):
            return line.split(maxsplit=1)[1]
    return None


class TestMsmtprcCaTrust(unittest.TestCase):
    def test_a_container_of_a_self_signed_app_names_the_mounted_ca(self):
        rendered = _render(
            in_container=True, ca_injected=True, application_id="web-app-moodle"
        )
        self.assertEqual(_trust_line(rendered), CA_CONTAINER)

    def test_a_container_without_the_injected_ca_names_nothing(self):
        rendered = _render(
            in_container=True, ca_injected=False, application_id="web-app-moodle"
        )
        self.assertIsNone(_trust_line(rendered))

    def test_the_host_render_names_nothing_and_never_needs_an_application(self):
        rendered = _render(in_container=False, ca_injected=True)
        self.assertIsNone(_trust_line(rendered))

    def test_no_render_path_names_a_host_resolved_bundle(self):
        for in_container, injected in ((True, True), (True, False), (False, True)):
            extra = {"application_id": "web-app-moodle"} if in_container else {}
            rendered = _render(in_container=in_container, ca_injected=injected, **extra)
            trust = _trust_line(rendered)
            self.assertIn(trust, (None, CA_CONTAINER), f"host path leaked: {trust}")


class TestMsmtprcOnionProxy(unittest.TestCase):
    """Reaching a .onion relay at all.

    A .onion peer has no route off the node, so msmtp has to hand the connection
    to Tor's SOCKS5 listener. Without it every send fails "cannot connect ...
    Connection refused" and the hlth-msmtp unit takes the deploy down with it.
    """

    ONION_EMAIL: ClassVar[dict[str, Any]] = dict(
        EMAIL, host="mail.abc123.onion", tls=False, port=25
    )

    def _proxy(self, rendered: str) -> dict[str, str]:
        found = {}
        for line in rendered.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in ("proxy_host", "proxy_port"):
                found[parts[0]] = parts[1]
        return found

    def test_a_clearnet_relay_names_no_proxy(self):
        rendered = _render(in_container=False, ca_injected=False)
        self.assertEqual(self._proxy(rendered), {})

    def test_an_onion_relay_is_reached_through_the_node_socks_listener(self):
        rendered = _render(
            in_container=False, ca_injected=False, email=self.ONION_EMAIL
        )
        self.assertEqual(
            self._proxy(rendered), {"proxy_host": "127.0.0.1", "proxy_port": "9050"}
        )

    def test_a_rig_loopback_target_is_never_routed_through_tor(self):
        """Inside the rig smtp_host returns loopback even when the provider's canonical
        is an onion. Gating the proxy on email.host instead of the dialled host sent
        127.0.0.1 through Tor, and every send hung until the timeout killed it
        (rc=124)."""
        rendered = _render(
            in_container=False,
            ca_injected=False,
            email=self.ONION_EMAIL,
            smtp_host="127.0.0.1",
        )
        self.assertEqual(self._proxy(rendered), {})

    def test_a_container_render_reaches_tor_over_the_shared_endpoint(self):
        rendered = _render(
            in_container=True,
            ca_injected=False,
            email=self.ONION_EMAIL,
            application_id="web-app-moodle",
        )
        self.assertEqual(
            self._proxy(rendered), {"proxy_host": "tor", "proxy_port": "9050"}
        )


if __name__ == "__main__":
    unittest.main()

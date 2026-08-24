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

import unittest

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
    return env


def _render(*, in_container: bool, ca_injected: bool, **extra) -> str:
    def lookup(kind, *args, **kwargs):
        if kind == "email":
            return EMAIL
        if kind == "smtp_host":
            return "relay"
        if kind == "ca_injected":
            return ca_injected
        raise AssertionError(f"unexpected lookup: {kind}")

    template = _env().from_string(read_text(str(TEMPLATE)))
    return template.render(
        lookup=lookup,
        sys_svc_mail_msmtp_in_container=in_container,
        MODE_DEBUG=False,
        CA_TRUST={"inject_cert_container": CA_CONTAINER},
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


if __name__ == "__main__":
    unittest.main()

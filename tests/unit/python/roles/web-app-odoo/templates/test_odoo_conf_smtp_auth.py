from __future__ import annotations

import unittest
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

_TEMPLATE = "roles/web-app-odoo/templates/odoo.conf.j2"
_AUTH_KEYS = ("smtp_user", "smtp_password")


def _render(auth: bool) -> dict[str, str]:
    """
    Args:
      auth: the ``auth`` field the email lookup resolves for the SMTP listener.

    Returns:
      the rendered odoo.conf options as a key to value mapping.
    """
    email = {"enabled": True, "auth": auth, "from": "no-reply@example.test"}

    def _lookup(kind: str, *terms: object) -> object:
        """
        Args:
          kind: lookup plugin name the template calls.
          terms: positional terms of that lookup.

        Returns:
          the email fixture, a volume with a target, or a memory size.
        """
        if kind == "email":
            return email
        if kind == "volume":
            return SimpleNamespace(target=f"/var/lib/odoo/{terms[-1]}")
        if kind == "service_memory_mb":
            return 1024
        raise AssertionError(f"unexpected lookup({kind!r}, {terms!r})")

    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
    )
    env.filters["bool"] = bool
    text = env.get_template(_TEMPLATE).render(
        application_id="web-app-odoo",
        lookup=_lookup,
        container_port=8069,
        container_websocket_port=8072,
        ODOO_DB_HOST="db",
        ODOO_DB_PORT=5432,
        ODOO_DB_USER="odoo",
        ODOO_DB_PASSWORD="fixture",
        ODOO_DB_NAME="odoo",
        ODOO_MASTER_PASSWORD="fixture",
        ODOO_SMTP_HOST="mail.example.onion",
        ODOO_SMTP_PORT=25,
        ODOO_SMTP_USER="no-reply@example.test",
        ODOO_SMTP_PASSWORD="fixture",
        ODOO_SMTP_SSL=False,
        ODOO_REDIS_ENABLED=False,
    )
    return {
        key.strip(): value.strip()
        for key, _, value in (line.partition("=") for line in text.splitlines())
        if value
    }


class TestOdooConfSmtpAuth(unittest.TestCase):
    def test_a_listener_without_smtp_auth_gets_no_login(self) -> None:
        options = _render(auth=False)
        self.assertEqual(options["smtp_server"], "mail.example.onion")
        for key in _AUTH_KEYS:
            self.assertNotIn(key, options)

    def test_negative_control_a_listener_with_smtp_auth_gets_the_login(self) -> None:
        options = _render(auth=True)
        for key in _AUTH_KEYS:
            self.assertIn(key, options)


if __name__ == "__main__":
    unittest.main()

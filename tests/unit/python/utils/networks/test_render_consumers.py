from __future__ import annotations

import unittest
from typing import ClassVar

from utils.networks.render import _coerce_bool, _is_consumer

from ._render_helpers import (
    _const_lookup_config,
    _const_lookup_database,
    _role_lookup_config,
)


class TestCoerceBool(unittest.TestCase):
    def test_bool_passthrough(self):
        self.assertTrue(_coerce_bool(True))
        self.assertFalse(_coerce_bool(False))

    def test_string_truthy_set(self):
        for v in ("true", "True", "TRUE", "1", "yes", "Yes"):
            self.assertTrue(_coerce_bool(v), msg=v)

    def test_string_falsy_set(self):
        for v in ("false", "no", "0", "", "anything-else"):
            self.assertFalse(_coerce_bool(v), msg=v)

    def test_none_is_false(self):
        self.assertFalse(_coerce_bool(None))

    def test_other_truthy(self):
        self.assertTrue(_coerce_bool(1))
        self.assertTrue(_coerce_bool([0]))
        self.assertFalse(_coerce_bool(0))
        self.assertFalse(_coerce_bool([]))


class TestMcpClientConsumer(unittest.TestCase):
    """Only a client the provider admitted joins its network."""

    ADMITTED: ClassVar[dict] = {"services.qdrant.mcp_consumer": True}

    def _consumer(self, **flags):
        entry = {
            "role": "web-app-homeassistant",
            "overlay": {"consumer": {"kind": "mcp_client"}},
        }
        return _is_consumer(
            entry,
            "svc-db-qdrant",
            _const_lookup_config(**flags),
            _const_lookup_database(),
        )

    def test_client_joins(self):
        self.assertTrue(
            self._consumer(
                **{
                    "mcp.enabled": True,
                    "mcp.shared": True,
                    "mcp.direction": "client",
                    **self.ADMITTED,
                }
            )
        )

    def test_both_joins(self):
        self.assertTrue(
            self._consumer(
                **{
                    "mcp.enabled": True,
                    "mcp.shared": True,
                    "mcp.direction": "both",
                    **self.ADMITTED,
                }
            )
        )

    def test_server_stays_out(self):
        self.assertFalse(
            self._consumer(
                **{
                    "mcp.enabled": True,
                    "mcp.shared": True,
                    "mcp.direction": "server",
                }
            ),
            "a provider on another provider's network is the mesh this kind removes",
        )

    def test_disabled_stays_out(self):
        self.assertFalse(self._consumer(**{"mcp.direction": "client"}))

    def test_a_client_that_never_declared_itself_stays_out(self):
        self.assertFalse(
            self._consumer(
                **{
                    "mcp.enabled": True,
                    "mcp.shared": True,
                    "mcp.direction": "client",
                }
            ),
            "being a client is not an admission; the self-declaration decides",
        )

    def test_a_provider_that_states_nothing_admits_a_declared_client(self):
        """Only an explicit false refuses; an unset flag inherits the client's
        own declaration, and the accessor answers an unset path with false."""
        entry = {
            "role": "web-app-gitlab",
            "overlay": {"consumer": {"kind": "mcp_client"}},
        }
        self.assertTrue(
            _is_consumer(
                entry,
                "web-app-openwebui",
                _role_lookup_config(
                    {"web-app-openwebui": {"services.openwebui.mcp_consumer": True}},
                    **{
                        "mcp.enabled": True,
                        "mcp.shared": True,
                        "mcp.direction": "client",
                    },
                ),
                _const_lookup_database(),
            )
        )

    def test_a_provider_override_refuses_a_declared_client(self):
        entry = {
            "role": "web-app-homeassistant",
            "overlay": {"consumer": {"kind": "mcp_client"}},
        }
        self.assertFalse(
            _is_consumer(
                entry,
                "svc-db-qdrant",
                _role_lookup_config(
                    {"web-app-homeassistant": {"services.qdrant.mcp_consumer": False}},
                    **{
                        "mcp.enabled": True,
                        "mcp.shared": True,
                        "mcp.direction": "client",
                        "services.qdrant.mcp_consumer": True,
                    },
                ),
                _const_lookup_database(),
            )
        )


class TestConsumerKindList(unittest.TestCase):
    """A provider serving two kinds of consumer declares both on one overlay.

    Qdrant is the case: applications consume it as a vector database through the
    services flags, and MCP clients must reach its adapter. One overlay per role
    means a single `kind` cannot express both, and the second consumer silently
    has no route.
    """

    ENTRY: ClassVar[dict] = {
        "role": "svc-db-qdrant",
        "entity_name": "qdrant",
        "overlay": {
            "consumer": {"kind": ["services_flags", "mcp_client"], "key": "qdrant"}
        },
    }

    def _consumer(self, application_id, **flags):
        return _is_consumer(
            self.ENTRY,
            application_id,
            _const_lookup_config(**flags),
            _const_lookup_database(),
        )

    def test_a_service_consumer_still_joins(self):
        self.assertTrue(
            self._consumer(
                "web-app-openwebui",
                **{"services.qdrant.enabled": True, "services.qdrant.shared": True},
            )
        )

    def test_an_admitted_mcp_client_joins(self):
        self.assertTrue(
            self._consumer(
                "web-app-hermes",
                **{
                    "mcp.enabled": True,
                    "mcp.shared": True,
                    "mcp.direction": "client",
                    "services.hermes.mcp_consumer": True,
                },
            )
        )

    def test_a_role_matching_neither_kind_stays_out(self):
        self.assertFalse(self._consumer("web-app-unrelated"))


if __name__ == "__main__":
    unittest.main()

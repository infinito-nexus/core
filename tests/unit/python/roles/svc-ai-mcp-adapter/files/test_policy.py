"""Unit tests for the reusable MCP adapter's policy layer."""

from __future__ import annotations

import importlib.util
import json
import unittest

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/python/policy.py"

spec = importlib.util.spec_from_file_location("adapter_policy", MODULE_PATH)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

TOOLS = {
    "checkmk_list_hosts": {
        "method": "GET",
        "path": "/domain-types/host_config/collections/all",
    },
    "checkmk_get_host_status": {
        "method": "GET",
        "path": "/objects/host/{host}",
        "input_schema": {
            "type": "object",
            "properties": {"host": {"type": "string"}, "columns": {"type": "string"}},
            "required": ["host"],
        },
    },
}

LIMITS = {
    "request_bytes": 64,
    "response_bytes": 1048576,
    "timeout_seconds": 15,
    "concurrent_requests": 4,
    "page_size": 100,
    "result_items": 5,
    "stream_seconds": 300,
}


def contract(**overrides):
    base = {
        "provider": "web-app-checkmk",
        "upstream_url": "http://checkmk:5000",
        "auth_subject": "service_account",
        "tools": TOOLS,
        "limits": LIMITS,
        "schema_sha256": policy.schema_digest(TOOLS),
    }
    base.update(overrides)
    return base


class TestLoadContract(unittest.TestCase):
    def test_a_complete_contract_loads(self):
        loaded = policy.load_contract(json.dumps(contract()))
        self.assertEqual("web-app-checkmk", loaded["provider"])

    def test_non_json_is_refused(self):
        with self.assertRaises(policy.ContractError):
            policy.load_contract("not json")

    def test_a_missing_limit_is_refused_at_startup(self):
        broken = contract(
            limits={k: v for k, v in LIMITS.items() if k != "timeout_seconds"}
        )
        with self.assertRaises(policy.ContractError):
            policy.load_contract(json.dumps(broken))

    def test_a_non_positive_limit_is_refused(self):
        with self.assertRaises(policy.ContractError):
            policy.load_contract(
                json.dumps(contract(limits={**LIMITS, "page_size": 0}))
            )

    def test_an_empty_allowlist_is_refused(self):
        with self.assertRaises(policy.ContractError):
            policy.load_contract(json.dumps(contract(tools={})))

    def test_a_wildcard_path_is_refused(self):
        wild = {"anything": {"method": "GET", "path": "/objects/*"}}
        broken = contract(tools=wild, schema_sha256=policy.schema_digest(wild))
        with self.assertRaises(policy.ContractError):
            policy.load_contract(json.dumps(broken))

    def test_an_unpinned_schema_is_refused(self):
        with self.assertRaises(policy.ContractError):
            policy.load_contract(json.dumps(contract(schema_sha256="")))

    def test_a_declared_write_tool_is_refused_while_mutations_are_off(self):
        tools = {"x_translate": {"method": "POST", "path": "/translate"}}
        broken = contract(tools=tools, schema_sha256=policy.schema_digest(tools))
        with self.assertRaises(policy.ContractError) as error:
            policy.load_contract(json.dumps(broken))
        self.assertIn("mutations are off", str(error.exception))

    def test_a_declared_write_tool_loads_once_mutations_are_enabled(self):
        tools = {"x_translate": {"method": "POST", "path": "/translate"}}
        allowed = contract(
            tools=tools,
            schema_sha256=policy.schema_digest(tools),
            mutating_tools_enabled=True,
        )
        self.assertEqual(
            "x_translate",
            next(iter(policy.load_contract(json.dumps(allowed))["tools"])),
        )


class TestDrift(unittest.TestCase):
    def test_a_matching_hash_passes(self):
        policy.assert_no_drift(contract())

    def test_an_added_tool_fails_closed(self):
        drifted = dict(contract())
        drifted["tools"] = {
            **TOOLS,
            "checkmk_delete_host": {"method": "DELETE", "path": "/x"},
        }
        with self.assertRaises(policy.ContractError) as error:
            policy.assert_no_drift(drifted)
        self.assertIn(policy.DENY_SCHEMA_DRIFT, str(error.exception))


class TestAuthorizeClient(unittest.TestCase):
    def test_the_issued_bearer_is_accepted(self):
        policy.authorize_client("s3cret", "Bearer s3cret")

    def test_a_wrong_bearer_is_refused(self):
        with self.assertRaises(PermissionError):
            policy.authorize_client("s3cret", "Bearer other")

    def test_a_missing_header_is_refused(self):
        with self.assertRaises(PermissionError):
            policy.authorize_client("s3cret", "")

    def test_an_unset_bearer_refuses_everyone(self):
        with self.assertRaises(PermissionError):
            policy.authorize_client("", "Bearer anything")


class TestAuthorizeCall(unittest.TestCase):
    def test_a_listed_read_tool_resolves_to_its_upstream_operation(self):
        method, path = policy.authorize_call(contract(), "checkmk_list_hosts", {})
        self.assertEqual("GET", method)
        self.assertEqual("/domain-types/host_config/collections/all", path)

    def test_an_unlisted_tool_is_refused_by_name(self):
        with self.assertRaises(PermissionError) as error:
            policy.authorize_call(contract(), "checkmk_delete_host", {})
        self.assertIn(policy.DENY_UNKNOWN_TOOL, str(error.exception))

    def test_a_mutating_tool_is_refused_while_mutations_stay_off(self):
        tools = {"checkmk_activate": {"method": "POST", "path": "/activate"}}
        with self.assertRaises(PermissionError) as error:
            policy.authorize_call(contract(tools=tools), "checkmk_activate", {})
        self.assertIn(policy.DENY_MUTATION, str(error.exception))

    def test_a_mutating_tool_passes_once_explicitly_enabled(self):
        tools = {"checkmk_activate": {"method": "POST", "path": "/activate"}}
        method, _ = policy.authorize_call(
            contract(tools=tools, mutating_tools_enabled=True), "checkmk_activate", {}
        )
        self.assertEqual("POST", method)

    def test_an_oversized_argument_payload_is_refused(self):
        with self.assertRaises(PermissionError) as error:
            policy.authorize_call(contract(), "checkmk_list_hosts", {"f": "x" * 200})
        self.assertIn(policy.DENY_REQUEST_TOO_LARGE, str(error.exception))


class TestLimits(unittest.TestCase):
    def test_listed_tools_are_exactly_the_allowlist(self):
        self.assertEqual(sorted(TOOLS), policy.listed_tools(contract()))

    def test_a_page_size_above_the_ceiling_is_clamped(self):
        self.assertEqual(100, policy.clamp_page(contract(), 5000))

    def test_a_missing_page_size_falls_back_to_the_ceiling(self):
        self.assertEqual(100, policy.clamp_page(contract(), None))

    def test_a_page_size_below_one_is_raised_to_one(self):
        self.assertEqual(1, policy.clamp_page(contract(), 0))

    def test_results_are_truncated_to_the_contract_ceiling(self):
        self.assertEqual(5, len(policy.truncate_results(contract(), list(range(50)))))


class TestDeclaredArguments(unittest.TestCase):
    """A published input schema is enforced, not merely advertised.

    On the openapi path an argument the contract does not name is appended to
    the upstream request as a query parameter, so an unchecked schema lets a
    client add parameters the reviewed operation never granted.
    """

    def test_a_declared_argument_passes(self):
        method, path = policy.authorize_call(
            contract(), "checkmk_get_host_status", {"host": "web-01"}
        )
        self.assertEqual(("GET", "/objects/host/{host}"), (method, path))

    def test_an_optional_declared_argument_passes(self):
        policy.authorize_call(
            contract(),
            "checkmk_get_host_status",
            {"host": "web-01", "columns": "state"},
        )

    def test_an_undeclared_argument_is_refused(self):
        with self.assertRaises(PermissionError) as caught:
            policy.authorize_call(
                contract(),
                "checkmk_get_host_status",
                {"host": "web-01", "site": "other"},
            )
        self.assertIn(policy.DENY_UNKNOWN_ARGUMENT, str(caught.exception))

    def test_a_missing_required_argument_is_refused(self):
        with self.assertRaises(PermissionError) as caught:
            policy.authorize_call(contract(), "checkmk_get_host_status", {})
        self.assertIn(policy.DENY_MISSING_ARGUMENT, str(caught.exception))

    def test_a_tool_declaring_no_schema_takes_no_arguments(self):
        with self.assertRaises(PermissionError) as caught:
            policy.authorize_call(contract(), "checkmk_list_hosts", {"limit": 5000})
        self.assertIn(policy.DENY_UNKNOWN_ARGUMENT, str(caught.exception))

    def test_a_tool_declaring_no_schema_still_serves_a_bare_call(self):
        method, _path = policy.authorize_call(contract(), "checkmk_list_hosts", {})
        self.assertEqual("GET", method)


class TestAudit(unittest.TestCase):
    def test_the_event_names_both_sides_and_the_outcome(self):
        event = policy.audit_event(
            contract(), "web-app-openwebui", "checkmk_list_hosts", "ok", 12, "cid-1"
        )
        self.assertEqual("web-app-checkmk", event["provider"])
        self.assertEqual("web-app-openwebui", event["consumer"])
        self.assertEqual("ok", event["status"])
        self.assertEqual("cid-1", event["correlation_id"])

    def test_the_event_carries_neither_arguments_nor_payload(self):
        event = policy.audit_event(
            contract(), "web-app-openwebui", "checkmk_list_hosts", "ok", 12, "cid-1"
        )
        self.assertEqual(
            {
                "provider",
                "consumer",
                "tool",
                "subject",
                "status",
                "duration_ms",
                "correlation_id",
            },
            set(event),
        )


class TestUpstreamUrl(unittest.TestCase):
    """A provider that keys its endpoint by URL segment instead of by header.

    The secret must not reach the contract, because the contract is rendered
    into the compose file; it arrives through the same env file the header
    credential uses and is spliced in here.
    """

    BASE = "http://baserow:80/mcp"

    def test_without_a_path_key_the_url_is_returned_untouched(self) -> None:
        self.assertEqual(policy.upstream_url(self.BASE), self.BASE)

    def test_a_trailing_slash_survives_when_nothing_is_appended(self) -> None:
        self.assertEqual(policy.upstream_url(self.BASE + "/"), self.BASE + "/")

    def test_a_path_key_is_appended_as_its_own_segment(self) -> None:
        self.assertEqual(
            policy.upstream_url(self.BASE, "abc123"),
            "http://baserow:80/mcp/abc123",
        )

    def test_a_suffix_follows_the_key(self) -> None:
        self.assertEqual(
            policy.upstream_url(self.BASE, "abc123", "sse"),
            "http://baserow:80/mcp/abc123/sse",
        )

    def test_a_suffix_without_a_key_still_lands(self) -> None:
        self.assertEqual(
            policy.upstream_url(self.BASE, "", "sse"),
            "http://baserow:80/mcp/sse",
        )

    def test_a_trailing_slash_does_not_double_up(self) -> None:
        self.assertEqual(
            policy.upstream_url(self.BASE + "/", "abc123", "/sse/"),
            "http://baserow:80/mcp/abc123/sse",
        )

    def test_a_key_carrying_url_syntax_is_escaped(self) -> None:
        self.assertEqual(
            policy.upstream_url(self.BASE, "a/b?c=d"),
            "http://baserow:80/mcp/a%2Fb%3Fc%3Dd",
        )


if __name__ == "__main__":
    unittest.main()

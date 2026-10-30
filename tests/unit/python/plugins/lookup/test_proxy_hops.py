"""Unit tests for plugins/lookup/proxy_hops.py."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup.proxy_hops import LookupModule

_SUBNETS = {
    "web-app-nextcloud": "192.168.41.0/24",
    "svc-db-mariadb": "192.168.201.0/24",
    "svc-prx-openresty": "192.168.107.0/24",
}


class _Templar:
    def __init__(self, vars_=None):
        self.available_variables = vars_ or {}

    def template(self, value, **_):
        return value


def _make_lookup(vars_):
    lm = LookupModule()
    lm._templar = _Templar(vars_)
    lm._loader = mock.MagicMock()
    return lm


def _role_subnets():
    return mock.MagicMock(
        run=lambda terms, **_: [[_SUBNETS[role] for role in terms[0]]]
    )


def _joined(application_id, deployment_mode, **_):
    if application_id == "svc-prx-openresty":
        return ["svc-prx-openresty"] if deployment_mode == "swarm" else []
    if deployment_mode == "swarm":
        return ["svc-db-mariadb", "svc-prx-openresty", application_id]
    return ["svc-db-mariadb", application_id]


def _run(mode, terms=("web-app-nextcloud",), joined=_joined):
    vars_ = {"application_id": "web-app-nextcloud", "DEPLOYMENT_MODE": mode}
    lm = _make_lookup(vars_)
    with (
        mock.patch(
            "utils.networks.lookup_context.build_service_registry_from_applications",
            return_value={},
        ),
        mock.patch("utils.networks.lookup_context.lookup_loader") as context_loader,
        mock.patch("plugins.lookup.proxy_hops.lookup_loader") as plugin_loader,
        mock.patch(
            "plugins.lookup.proxy_hops.compute_external_network_roles",
            side_effect=lambda **kwargs: joined(
                kwargs["application_id"], kwargs["deployment_mode"]
            ),
        ) as roles_mock,
    ):
        context_loader.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [""])
        plugin_loader.get.return_value = _role_subnets()
        result = lm.run(list(terms), variables=vars_)
    return result, roles_mock


class TestProxyHopsLookup(unittest.TestCase):
    def test_raises_without_application_id_term(self):
        lm = _make_lookup({"DEPLOYMENT_MODE": "compose"})
        with self.assertRaises(AnsibleError):
            lm.run([], variables={})

    def test_raises_on_extra_terms(self):
        lm = _make_lookup({"DEPLOYMENT_MODE": "compose"})
        with self.assertRaises(AnsibleError):
            lm.run(["web-app-nextcloud", "extra"], variables={})

    def test_compose_returns_gateways_of_the_joined_networks(self):
        result, _ = _run("compose")
        self.assertEqual(result, [["192.168.41.1", "192.168.201.1"]])

    def test_swarm_returns_the_overlay_shared_with_openresty(self):
        result, roles_mock = _run("swarm")
        self.assertEqual(result, [["192.168.107.0/24"]])
        asked = {call.kwargs["application_id"] for call in roles_mock.call_args_list}
        self.assertEqual(asked, {"web-app-nextcloud", "svc-prx-openresty"})

    def test_missing_shared_overlay_surfaces_as_ansible_error(self):
        def isolated(application_id, deployment_mode):
            return [application_id]

        with self.assertRaises(AnsibleError):
            _run("swarm", joined=isolated)


if __name__ == "__main__":
    unittest.main()

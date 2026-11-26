from __future__ import annotations

import unittest

from ansible.errors import AnsibleError

from plugins.lookup import container_address, container_service, image

from .test_container_address import _run as _run_address
from .test_container_service import _run as _run_service
from .test_image import _run as _run_image

APPLICATION = "web-app-mattermost"
SERVICE = "mattermost"
SERVICE_LOOKUPS = (
    ("container_address", container_address.LookupModule, _run_address),
    ("container_service", container_service.LookupModule, _run_service),
    ("image", image.LookupModule, _run_image),
)
CONTAINER_LOOKUPS = SERVICE_LOOKUPS[:2]


class TestServiceLookupContract(unittest.TestCase):
    def _each_refuses(self, application_id: str, service_key: str) -> None:
        for name, _lookup, run in SERVICE_LOOKUPS:
            with self.subTest(lookup=name), self.assertRaises(AnsibleError):
                run(application_id, service_key)

    def test_missing_terms_raise(self):
        for name, lookup, _run in SERVICE_LOOKUPS:
            for terms in ([], [APPLICATION], [APPLICATION, SERVICE, "extra"]):
                with (
                    self.subTest(lookup=name, terms=terms),
                    self.assertRaises(AnsibleError),
                ):
                    lookup().run(terms, variables={})

    def test_empty_application_id_raises(self):
        self._each_refuses("", SERVICE)

    def test_empty_service_key_raises(self):
        self._each_refuses(APPLICATION, "")

    def test_unknown_application_raises(self):
        self._each_refuses("web-app-missing", SERVICE)

    def test_unknown_service_raises(self):
        self._each_refuses(APPLICATION, "smtp")

    def test_compose_mode_returns_bare_name(self):
        for name, _lookup, run in CONTAINER_LOOKUPS:
            with self.subTest(lookup=name):
                out = run(
                    APPLICATION, SERVICE, variables={"DEPLOYMENT_MODE": "compose"}
                )
                self.assertEqual(out, [SERVICE])

    def test_compose_mode_defaults_when_deployment_mode_missing(self):
        for name, _lookup, run in CONTAINER_LOOKUPS:
            with self.subTest(lookup=name):
                self.assertEqual(run(APPLICATION, SERVICE, variables={}), [SERVICE])

    def test_service_with_empty_name_raises(self):
        apps = {APPLICATION: {"services": {SERVICE: {"name": ""}}}}
        for name, _lookup, run in CONTAINER_LOOKUPS:
            with self.subTest(lookup=name), self.assertRaises(AnsibleError):
                run(
                    APPLICATION,
                    SERVICE,
                    variables={"DEPLOYMENT_MODE": "compose"},
                    applications=apps,
                )


if __name__ == "__main__":
    unittest.main()

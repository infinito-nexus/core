import os
import unittest
from unittest import mock

from utils.tests.swarm import lab

_PAYLOADS = {
    "svc-db-postgres": {
        "services": {"tor": {"enabled": True}, "postgres": {"exposed": True}}
    },
    "web-app-gitlab": {"services": {"gitlab": {"exposed": True}}},
}


class TestWithoutEngineExposure(unittest.TestCase):
    def test_an_ha_lab_unexposes_the_engine_only(self):
        with mock.patch.dict(os.environ, {"INFINITO_SWARM_DB_TOPOLOGY": "ha"}):
            payloads = lab.without_engine_exposure(_PAYLOADS)
        self.assertFalse(payloads["svc-db-postgres"]["services"]["postgres"]["exposed"])
        self.assertTrue(payloads["svc-db-postgres"]["services"]["tor"]["enabled"])
        self.assertTrue(payloads["web-app-gitlab"]["services"]["gitlab"]["exposed"])
        self.assertTrue(_PAYLOADS["svc-db-postgres"]["services"]["postgres"]["exposed"])

    def test_a_standalone_lab_keeps_the_exposure(self):
        with mock.patch.dict(os.environ, {"INFINITO_SWARM_DB_TOPOLOGY": "standalone"}):
            payloads = lab.without_engine_exposure(_PAYLOADS)
        self.assertTrue(payloads["svc-db-postgres"]["services"]["postgres"]["exposed"])


if __name__ == "__main__":
    unittest.main()

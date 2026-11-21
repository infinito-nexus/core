from __future__ import annotations

import importlib
import os
import sys
import unittest
import unittest.mock as mock

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-access-request" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

entry = importlib.import_module("access_request.__main__")


class TestMain(unittest.TestCase):
    def test_the_service_listens_on_the_configured_port(self):
        application = object()
        with (
            mock.patch.dict(os.environ, {"ACCESS_REQUEST_PORT": "8000"}),
            mock.patch.object(entry, "from_environment", return_value=application),
            mock.patch.object(entry, "make_server") as make_server,
        ):
            entry.main()

        make_server.assert_called_once()
        _, port, served = make_server.call_args.args
        self.assertEqual(8000, port)
        self.assertIs(application, served)
        server = make_server.return_value.__enter__.return_value
        server.serve_forever.assert_called_once_with()

    def test_a_missing_port_stops_the_start(self):
        environment = {
            k: v for k, v in os.environ.items() if k != "ACCESS_REQUEST_PORT"
        }
        with (
            mock.patch.dict(os.environ, environment, clear=True),
            mock.patch.object(entry, "make_server") as make_server,
            self.assertRaises(KeyError),
        ):
            entry.main()

        make_server.assert_not_called()


if __name__ == "__main__":
    unittest.main()

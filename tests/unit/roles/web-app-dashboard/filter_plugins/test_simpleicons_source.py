import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch

import certifi

from . import PROJECT_ROOT


def _load_simpleicons_module():
    module_path = (
        PROJECT_ROOT
        / "roles"
        / "web-app-dashboard"
        / "filter_plugins"
        / "simpleicons_source.py"
    )

    if not module_path.is_file():
        raise RuntimeError(
            f"Could not find simpleicons_source.py at expected path: {module_path}"
        )

    spec = importlib.util.spec_from_file_location("simpleicons_source", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_simpleicons = _load_simpleicons_module()
get_requests_verify = _simpleicons.get_requests_verify
add_simpleicon_source = _simpleicons.add_simpleicon_source


class TestGetRequestsVerify(unittest.TestCase):
    def test_uses_explicit_requests_ca_bundle_when_present(self):
        with (
            tempfile.NamedTemporaryFile() as handle,
            patch.dict(os.environ, {"REQUESTS_CA_BUNDLE": handle.name}, clear=False),
        ):
            self.assertEqual(get_requests_verify(), handle.name)

    def test_falls_back_to_certifi_bundle_when_no_env_ca_exists(self):
        with patch.dict(
            os.environ,
            {
                "REQUESTS_CA_BUNDLE": "",
                "SSL_CERT_FILE": "",
                "CA_TRUST_CERT_HOST": "",
            },
            clear=False,
        ):
            self.assertEqual(get_requests_verify(), certifi.where())

    def test_ignores_missing_env_bundle_and_keeps_verification_enabled(self):
        with patch.dict(
            os.environ,
            {"REQUESTS_CA_BUNDLE": "/definitely/missing/ca.pem"},
            clear=False,
        ):
            self.assertEqual(get_requests_verify(), certifi.where())


class TestAddSimpleiconSource(unittest.TestCase):
    def test_uses_probe_url_for_source_when_no_public_url_base_given(self):
        cards = [{"title": "Keycloak", "icon": {"class": "fa-solid fa-lock"}}]

        with (
            patch.object(
                _simpleicons, "get_requests_verify", return_value="/tmp/test-ca.crt"
            ),
            patch.object(_simpleicons.requests, "head") as mock_head,
        ):
            mock_head.return_value.status_code = 200

            result = add_simpleicon_source(cards, "https://icons.example")

        self.assertEqual(
            result[0]["icon"]["source"], "https://icons.example/keycloak.svg"
        )
        self.assertEqual(result[0]["icon"]["class"], "fa-solid fa-lock")
        mock_head.assert_called_once_with(
            "https://icons.example/keycloak.svg",
            timeout=2,
            allow_redirects=True,
            verify="/tmp/test-ca.crt",
        )

    def test_probes_sync_url_but_writes_public_url_into_source(self):
        cards = [{"title": "Keycloak", "icon": {}}]

        with patch.object(_simpleicons.requests, "head") as mock_head:
            mock_head.return_value.status_code = 200

            result = add_simpleicon_source(
                cards,
                "http://172.17.0.1:8044/",
                public_url_base="https://icon.example.com",
            )

        # HEAD goes against the internal sync URL (no TLS, no redirect).
        mock_head.assert_called_once()
        probed_url = mock_head.call_args.args[0]
        self.assertEqual(probed_url, "http://172.17.0.1:8044/keycloak.svg")
        # The browser-facing source carries the public URL.
        self.assertEqual(
            result[0]["icon"]["source"], "https://icon.example.com/keycloak.svg"
        )

    def test_keeps_card_without_source_when_icon_does_not_exist(self):
        cards = [{"title": "Missing", "icon": {"class": "fa-solid fa-circle-question"}}]

        with patch.object(_simpleicons.requests, "head") as mock_head:
            mock_head.return_value.status_code = 404

            result = add_simpleicon_source(
                cards,
                "http://172.17.0.1:8044/",
                public_url_base="https://icon.example.com",
            )

        self.assertNotIn("source", result[0]["icon"])
        mock_head.assert_called_once()


if __name__ == "__main__":
    unittest.main()

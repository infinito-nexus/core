#!/usr/bin/env python3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.cert_utils import CertUtils


def _san_block(*entries):
    """
    Helper: builds a minimal OpenSSL text snippet that contains SAN entries.
    Example: _san_block('example.com', '*.example.com')
    """
    sans = ", ".join(f"DNS:{e}" for e in entries)
    return f"""
Certificate:
    Data:
        Version: 3 (0x2)
        ...
        X509v3 extensions:
            X509v3 Subject Alternative Name:
                {sans}
    """


class TestCertUtilsFindNewest(unittest.TestCase):
    def setUp(self):
        # Reset internal caches before each test
        CertUtils._domain_cert_mapping = None
        CertUtils._cert_snapshot = None

    def _mock_stat_map(self, mtime_map, size_map=None):
        size_map = size_map or {}

        def _stat_side_effect(path):
            return SimpleNamespace(
                st_mtime=mtime_map.get(path, 0.0),
                st_size=size_map.get(path, 1234),
            )

        return _stat_side_effect

    def test_prefers_newest_by_not_before(self):
        """
        Two certs with the same SAN 'www.example.com':
        - a/cert.pem: older notBefore
        - b/cert.pem: newer notBefore -> should be selected
        """
        files = [
            "/etc/letsencrypt/live/a/cert.pem",
            "/etc/letsencrypt/live/b/cert.pem",
        ]
        san_text = _san_block("www.example.com")

        with (
            patch.object(CertUtils, "list_cert_files", return_value=files),
            patch.object(CertUtils, "run_openssl", return_value=san_text),
            patch.object(CertUtils, "run_openssl_dates") as mock_dates,
            patch(
                "os.stat",
                side_effect=self._mock_stat_map(
                    {
                        files[0]: 1000,
                        files[1]: 1001,
                    }
                ),
            ),
        ):
            mock_dates.side_effect = [(10, 100000), (20, 100000)]  # older/newer

            folder = CertUtils.find_cert_for_domain(
                "www.example.com", "/etc/letsencrypt/live", debug=False
            )
            self.assertEqual(
                folder, "b", "Should return the folder with the newest notBefore date."
            )

    def test_fallback_to_mtime_when_not_before_missing(self):
        """
        When not_before is missing, mtime should be used as a fallback.
        """
        files = [
            "/etc/letsencrypt/live/a/cert.pem",
            "/etc/letsencrypt/live/b/cert.pem",
        ]
        san_text = _san_block("www.example.com")

        with (
            patch.object(CertUtils, "list_cert_files", return_value=files),
            patch.object(CertUtils, "run_openssl", return_value=san_text),
            patch.object(CertUtils, "run_openssl_dates", return_value=(None, None)),
            patch(
                "os.stat",
                side_effect=self._mock_stat_map(
                    {
                        files[0]: 1000,
                        files[1]: 2000,
                    }
                ),
            ),
        ):
            folder = CertUtils.find_cert_for_domain(
                "www.example.com", "/etc/letsencrypt/live", debug=False
            )
            self.assertEqual(
                folder, "b", "Should fall back to mtime and select the newest file."
            )

    def test_exact_beats_wildcard_even_if_wildcard_newer(self):
        """
        Exact matches must take precedence over wildcard matches,
        even if the wildcard certificate is newer.
        """
        files = [
            "/etc/letsencrypt/live/exact/cert.pem",
            "/etc/letsencrypt/live/wild/cert.pem",
        ]
        text_exact = _san_block("api.example.com")
        text_wild = _san_block("*.example.com")

        with (
            patch.object(CertUtils, "list_cert_files", return_value=files),
            patch.object(CertUtils, "run_openssl") as mock_text,
            patch.object(CertUtils, "run_openssl_dates") as mock_dates,
            patch(
                "os.stat",
                side_effect=self._mock_stat_map(
                    {
                        files[0]: 1000,  # exact is older
                        files[1]: 5000,  # wildcard is much newer
                    }
                ),
            ),
        ):
            mock_text.side_effect = [text_exact, text_wild]
            mock_dates.side_effect = [(10, 100000), (99, 100000)]

            folder = CertUtils.find_cert_for_domain(
                "api.example.com", "/etc/letsencrypt/live", debug=False
            )
            self.assertEqual(
                folder,
                "exact",
                "Exact match must win even if the wildcard certificate is newer.",
            )

    def test_wildcard_one_label_only(self):
        """
        Wildcards (*.example.com) must only match one additional label.
        """
        files = ["/etc/letsencrypt/live/wild/cert.pem"]
        text_wild = _san_block("*.example.com")

        with (
            patch.object(CertUtils, "list_cert_files", return_value=files),
            patch.object(CertUtils, "run_openssl", return_value=text_wild),
            patch.object(CertUtils, "run_openssl_dates", return_value=(50, 100000)),
            patch("os.stat", side_effect=self._mock_stat_map({files[0]: 1000})),
        ):
            # should match
            self.assertEqual(
                CertUtils.find_cert_for_domain(
                    "api.example.com", "/etc/letsencrypt/live"
                ),
                "wild",
            )
            # too deep -> should not match
            self.assertIsNone(
                CertUtils.find_cert_for_domain(
                    "deep.api.example.com", "/etc/letsencrypt/live"
                ),
                "Wildcard must not match multiple labels.",
            )
            # base domain not covered
            self.assertIsNone(
                CertUtils.find_cert_for_domain("example.com", "/etc/letsencrypt/live"),
                "Base domain is not covered by *.example.com.",
            )

    def test_snapshot_refresh_rebuilds_mapping(self):
        """
        ensure_cert_mapping() should rebuild mapping when snapshot changes.
        """
        CertUtils._domain_cert_mapping = {
            "www.example.com": [{"folder": "old", "mtime": 1, "not_before": 1}]
        }

        with (
            patch.object(CertUtils, "snapshot_changed", return_value=True),
            patch.object(CertUtils, "refresh_cert_mapping") as mock_refresh,
        ):

            def _set_new_mapping(cert_base_path, debug=False):
                CertUtils._domain_cert_mapping = {
                    "www.example.com": [
                        {"folder": "new", "mtime": 999, "not_before": 999}
                    ]
                }

            mock_refresh.side_effect = _set_new_mapping

            folder = CertUtils.find_cert_for_domain(
                "www.example.com", "/etc/letsencrypt/live", debug=False
            )
            self.assertEqual(
                folder, "new", "Mapping must be refreshed when snapshot changes."
            )


if __name__ == "__main__":
    unittest.main()

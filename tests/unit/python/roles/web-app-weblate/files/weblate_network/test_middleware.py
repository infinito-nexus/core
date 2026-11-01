from __future__ import annotations

import unittest

from ._stand_ins import (
    CALLBACK,
    CLEARNET,
    ONION,
    SITE_URL,
    DisallowedHostError,
    FakeRequest,
    UpstreamProxyMiddleware,
    load_shipped,
)


class TestNetworkProxyMiddleware(unittest.TestCase):
    def setUp(self) -> None:
        module = load_shipped()["middleware"]
        self.middleware = module.NetworkProxyMiddleware(lambda request: None)

    def test_it_subclasses_upstream(self) -> None:
        self.assertIsInstance(self.middleware, UpstreamProxyMiddleware)

    def test_an_onion_request_builds_onion_urls(self) -> None:
        request = FakeRequest(ONION, secure=False)
        self.middleware.process_request(request)
        self.assertEqual(
            request.build_absolute_uri(CALLBACK),
            f"http://{ONION}{CALLBACK}",
            "upstream pins every absolute URL to SITE_URL, which sends an onion "
            "visitor to the clearnet host",
        )

    def test_a_clearnet_request_stays_on_https(self) -> None:
        request = FakeRequest(CLEARNET, secure=True)
        self.middleware.process_request(request)
        self.assertEqual(request.build_absolute_uri(CALLBACK), f"{SITE_URL}{CALLBACK}")

    def test_the_internal_service_name_keeps_its_port(self) -> None:
        request = FakeRequest("weblate:8080", secure=False)
        self.middleware.process_request(request)
        self.assertEqual(
            request.build_absolute_uri("/api/"), "http://weblate:8080/api/"
        )

    def test_a_host_outside_allowed_hosts_is_refused(self) -> None:
        with self.assertRaises(DisallowedHostError):
            self.middleware.process_request(FakeRequest("evil.example", secure=True))

    def test_the_upstream_proxy_address_handling_still_runs(self) -> None:
        request = FakeRequest(
            ONION, secure=False, meta={"HTTP_X_FORWARDED_FOR": "203.0.113.7, 10.0.0.1"}
        )
        self.middleware.process_request(request)
        self.assertEqual(request.META["REMOTE_ADDR"], "203.0.113.7")


if __name__ == "__main__":
    unittest.main()

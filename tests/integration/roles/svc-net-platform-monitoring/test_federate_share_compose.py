from __future__ import annotations

import hashlib
import json
import os
import secrets
import ssl
import subprocess
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlencode

from utils.cache.files import PROJECT_ROOT
from utils.platform_monitoring import FEDERATED, KINDS

URL = os.environ.get("PLATFORM_MONITORING_FEDERATE_URL", "")
APPS = "web-app-prometheus,svc-net-platform-monitoring"
ROLE = "svc-net-platform-monitoring"
WIDE = ('{__name__=~".+"}',)
SERIES = {
    "health": ("infinito_hlth_", "nginx_stack_up"),
    "system": ("node_", "container_"),
    "traffic": ("nginx_http_",),
}


def deploy(share, digest):
    """Args:
    share: the ``platform_monitoring`` the compose deploy gets.
    digest: the SHA-256 hex digest of the bearer ``/federate`` admits.
    """
    extra = {
        "platform_monitoring": share,
        "applications": {
            ROLE: {"secrets": {"credentials": {"federation_token_sha256": digest}}}
        },
    }
    subprocess.run(
        ["make", "compose-deploy", "mode=update", f"apps={APPS}"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "INFINITO_INVENTORY_EXTRA_VARS": json.dumps(extra)},
        check=True,
    )


def federate(token, matches=WIDE):
    """Args:
    token: the bearer sent, None for none.
    matches: the ``match[]`` selectors the caller asks for.

    Returns:
        ``(status, metric names)`` of the answer.
    """
    query = urlencode([("match[]", match) for match in matches])
    request = urllib.request.Request(f"{URL}?{query}")  # noqa: S310 - URL is the operator-set https /federate endpoint of the local stack
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, context=context, timeout=30) as answer:  # noqa: S310 - the request above targets the operator-set https /federate endpoint
            body = answer.read().decode("utf-8")
            status = answer.status
    except urllib.error.HTTPError as error:
        return error.code, set()
    names = {
        line.split("{", 1)[0].split(" ", 1)[0]
        for line in body.splitlines()
        if line and not line.startswith("#")
    }
    return status, names


def holds(names, kind):
    return any(name.startswith(SERIES[kind]) for name in names)


@unittest.skipUnless(
    URL,
    "needs a compose stack and PLATFORM_MONITORING_FEDERATE_URL, "
    "e.g. https://prometheus.<DOMAIN_PRIMARY>/federate",
)
class FederateShareComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = secrets.token_urlsafe(32)
        cls.digest = hashlib.sha256(cls.token.encode("utf-8")).hexdigest()

    def test_each_kind_switched_off_leaves_federate_without_its_series(self):
        for kind in FEDERATED:
            with self.subTest(kind):
                deploy({**dict.fromkeys(KINDS, True), kind: False}, self.digest)
                status, names = federate(self.token)
                self.assertEqual(status, 200)
                self.assertFalse(holds(names, kind), sorted(names))
                for other in FEDERATED:
                    if other != kind:
                        self.assertTrue(holds(names, other), (other, sorted(names)))

    def test_a_wrong_or_missing_bearer_is_refused(self):
        deploy({}, self.digest)
        self.assertEqual(federate(None)[0], 401)
        self.assertEqual(federate(secrets.token_urlsafe(32))[0], 401)
        self.assertEqual(federate(self.token)[0], 200)

    def test_all_three_off_serves_no_federate(self):
        deploy(dict.fromkeys(FEDERATED, False), self.digest)
        self.assertEqual(federate(self.token)[0], 404)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
SERVICES = ROLE / ROLE_FILE_META_SERVICES
FLOOR = (2, 20, 1)
RELEASE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SQUID = "ubuntu/squid"
SQUID_TAG = re.compile(r"^\d+\.\d+-24\.04_(?P<channel>[a-z]+)$")
CHANNELS = ("stable", "candidate", "beta", "edge")
PUBLISHED = ("beta", "edge")


def egress_findings(image, version):
    """Args:
    image: ``services.egress.image`` of ``meta/services.yml``.
    version: ``services.egress.version`` beside it.

    Returns:
        Why the pin is not a Squid release on Ubuntu 24.04 in the most stable
        published channel.
    """
    best = next(channel for channel in CHANNELS if channel in PUBLISHED)
    match = SQUID_TAG.match(str(version))
    if image != SQUID or not match or match["channel"] != best:
        return [f"{image}:{version} is no {SQUID}:<release>-24.04_{best}"]
    return []


def pin_findings(version):
    """Args:
    version: ``semaphore.version`` of ``meta/services.yml``.

    Returns:
        Why the pin is no released tag of at least v2.20.1.
    """
    match = RELEASE.match(str(version))
    if not match:
        return [f"{version!r} is no release tag like v2.20.24"]
    if tuple(int(part) for part in match.groups()) < FLOOR:
        return [f"{version} is below v{'.'.join(map(str, FLOOR))}"]
    return []


class TestVersionPin(unittest.TestCase):
    def test_the_pin_is_a_release_of_at_least_2_20_1(self):
        services = load_yaml_str(read_text(str(SERVICES)))
        self.assertEqual(pin_findings(services["semaphore"]["version"]), [])

    def test_negative_control_each_weaker_pin_is_reported(self):
        for version in (
            "v2.20.0",
            "v2.19.17",
            "develop",
            "latest",
            "v2.21.0-beta1",
            "2.20.24",
        ):
            with self.subTest(version):
                self.assertTrue(pin_findings(version))

    def test_the_egress_proxy_runs_the_most_stable_squid_channel(self):
        egress = load_yaml_str(read_text(str(SERVICES)))["egress"]
        self.assertEqual(egress_findings(egress["image"], egress["version"]), [])

    def test_negative_control_a_less_stable_or_moving_squid_tag_is_reported(self):
        for image, version in (
            (SQUID, "6.6-24.04_edge"),
            (SQUID, "latest"),
            (SQUID, "6.6-24.04"),
            ("ubuntu/nginx", "6.6-24.04_beta"),
        ):
            with self.subTest(image=image, version=version):
                self.assertTrue(egress_findings(image, version))


if __name__ == "__main__":
    unittest.main()

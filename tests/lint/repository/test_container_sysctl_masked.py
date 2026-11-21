"""Lint: every privileged systemd container of the DiD, swarm and infra stacks
masks systemd-sysctl.service.

A privileged container mounts /proc/sys read-write, so the systemd-sysctl it
boots applies the image's vendor sysctl.d files to the host kernel, among them
Debian's `kernel.core_pattern=core`. The infinito image masks the unit in the
root Dockerfile, the swarm node and the infra runner inherit it from that
image, and the target image masks it in its init script."""

import re
import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

UNIT = "systemd-sysctl.service"
MASKERS = ("Dockerfile", "compose/target/init.sh")
INHERITORS = {
    "compose/swarm/Dockerfile": re.compile(
        r"^FROM \$\{INFINITO_IMAGE\}\s*$", re.MULTILINE
    ),
    "compose/infra.yml": re.compile(r"image: \"\$\{INFINITO_IMAGE[:?}]"),
}
COMPOSE_FILES = (
    "compose.yml",
    "compose/swarm/compose.yml",
    "compose/infra.yml",
)
MASKED_BUILD_CONTEXTS = {".", "compose/target"}


def _masks(text, unit=UNIT):
    joined = re.sub(r"\\\n", " ", text)
    return any(
        "systemctl mask" in line and unit in line.split()
        for line in joined.splitlines()
    )


def _unmasked_privileged(services):
    offenders = []
    for name, service in (services or {}).items():
        if not isinstance(service, dict) or not service.get("privileged"):
            continue
        build = service.get("build")
        context = build.get("context") if isinstance(build, dict) else build
        image = str(service.get("image", ""))
        if context in MASKED_BUILD_CONTEXTS or image.startswith("${INFINITO_IMAGE"):
            continue
        offenders.append(name)
    return offenders


class TestContainerSysctlMasked(unittest.TestCase):
    def test_images_mask_systemd_sysctl(self):
        for path in MASKERS:
            with self.subTest(path=path):
                self.assertTrue(_masks(read_text(str(PROJECT_ROOT / path))))

    def test_derived_images_inherit_the_mask(self):
        for path, pattern in INHERITORS.items():
            with self.subTest(path=path):
                self.assertRegex(read_text(str(PROJECT_ROOT / path)), pattern)

    def test_every_privileged_service_runs_a_masked_image(self):
        for path in COMPOSE_FILES:
            services = load_yaml_any(str(PROJECT_ROOT / path)).get("services", {})
            with self.subTest(path=path):
                self.assertTrue(any(s.get("privileged") for s in services.values()))
                self.assertEqual(_unmasked_privileged(services), [])

    def test_negative_control_a_dropped_mask_is_flagged(self):
        self.assertFalse(_masks("RUN systemctl mask getty.target \\\n    tmp.mount\n"))
        self.assertTrue(
            _masks("RUN systemctl mask getty.target \\\n    systemd-sysctl.service\n")
        )
        self.assertFalse(_masks("RUN systemctl unmask systemd-sysctl.service.d\n"))

    def test_negative_control_a_foreign_privileged_image_is_flagged(self):
        services = {"rogue": {"privileged": True, "image": "debian:13"}}
        self.assertEqual(_unmasked_privileged(services), ["rogue"])


if __name__ == "__main__":
    unittest.main()

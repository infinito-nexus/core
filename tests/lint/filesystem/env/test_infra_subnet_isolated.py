from __future__ import annotations

import re
import unittest
from ipaddress import IPv4Network
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files_with_content, read_text
from utils.infra import SUBNET_KEY

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

CIDR = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})(?![\d./])")
AGGREGATES = frozenset(
    IPv4Network(net)
    for net in ("0.0.0.0/0", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
RESERVED = tuple(
    IPv4Network(net) for net in ("172.30.0.0/16", "172.16.0.0/12", "192.168.0.0/16")
)
SCOPES = (
    "default.env",
    "compose/",
    "group_vars/",
    "inventories/",
    "roles/",
    "scripts/",
    "utils/",
    "cli/",
    ".github/",
)
EXTENSIONS = (".env", ".yml", ".yaml", ".j2", ".sh", ".py", ".conf", ".json")


def declared_subnet(default_env: str) -> IPv4Network:
    """Args:
    default_env: content of default.env.
    """
    line = next(
        line for line in default_env.splitlines() if line.startswith(f"{SUBNET_KEY}=")
    )
    return IPv4Network(line.split("=", 1)[1].strip())


def collisions(subnet: IPv4Network, texts: Iterable[tuple[str, str]]) -> list[str]:
    """Args:
        subnet: the infra /24.
        texts: (name, content) of every file that may declare a network.

    Returns:
        ``name: network`` for every declared network overlapping ``subnet``.
    """
    found: list[str] = []
    for name, text in texts:
        for line in text.splitlines():
            if line.startswith(f"{SUBNET_KEY}="):
                continue
            for match in CIDR.finditer(line):
                try:
                    network = IPv4Network(match.group(1), strict=False)
                except ValueError:
                    continue
                if network not in AGGREGATES and network.overlaps(subnet):
                    found.append(f"{name}: {network}")
    return found


def _repository_texts(root: Path) -> Iterable[tuple[str, str]]:
    for path, text in iter_project_files_with_content(
        extensions=EXTENSIONS, exclude_tests=True
    ):
        relative = Path(path).relative_to(root).as_posix()
        if relative.startswith(SCOPES):
            yield relative, text


class TestInfraSubnetIsolated(unittest.TestCase):
    def setUp(self) -> None:
        self.subnet = declared_subnet(read_text(str(PROJECT_ROOT / "default.env")))

    def test_the_subnet_is_a_slash_24_outside_the_slot_and_docker_pools(self) -> None:
        self.assertEqual(self.subnet.prefixlen, 24)
        for pool in RESERVED:
            self.assertFalse(self.subnet.overlaps(pool), str(pool))

    def test_no_network_the_repository_declares_overlaps_it(self) -> None:
        texts = list(_repository_texts(PROJECT_ROOT))
        names = {name for name, _text in texts}
        self.assertLessEqual({"default.env", "compose/infra.yml"}, names)
        self.assertTrue(collisions(IPv4Network("172.30.0.0/24"), texts))
        self.assertEqual(collisions(self.subnet, texts), [])

    def test_a_planted_overlap_is_found(self) -> None:
        planted = [("planted.yml", f"subnet: {self.subnet.network_address}/25")]
        self.assertEqual(len(collisions(self.subnet, planted)), 1)

    def test_a_slot_subnet_would_be_refused(self) -> None:
        self.assertTrue(IPv4Network("172.30.5.0/24").overlaps(RESERVED[0]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

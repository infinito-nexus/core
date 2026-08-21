"""Every declared image must end up with a healthcheck, from one side or the other.

A container without one is accepted as healthy the moment its process starts,
which is how a service that came back empty passes a restore drill. The probe
may come from the image itself; where it does not, the role has to declare one
in meta/services.yml so the compose file carries it.

The image side is read from the registry rather than by pulling: the manifest
names the config blob, the blob carries the ``HEALTHCHECK``. Probes run
concurrently and address the mirror first, falling back to the upstream
registry only for the images the mirror does not carry.

Without a configured mirror the sweep would put one request per declared image
straight onto Docker Hub and burn the anonymous rate limit for everything else
running on that address, so it refuses to run at all rather than degrade to
that.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.annotations.message import in_github_actions
from utils.annotations.suppress import is_suppressed_at
from utils.cache import PROJECT_ROOT
from utils.cache.files import iter_project_files_with_content, read_text
from utils.docker.image.discovery import iter_role_images, load_yaml
from utils.docker.mirror import mirror_image
from utils.docker.registry import image_healthcheck_probed
from utils.roles.mapping import ROLE_FILE_META_SERVICES

WORKERS = 16
MIRROR_PROBE = "redis"
RULE = "image-healthcheck"
HEALTHCHECK_IN_TEMPLATE = re.compile(
    r"healthcheck:|container_healthcheck|^\s*HEALTHCHECK\b", re.MULTILINE
)
INCLUDED_TEMPLATE = re.compile(
    r"""(?:include|lookup\(\s*['"]template['"]\s*,)\s*['"](roles/[^'"]+)['"]"""
)


def is_suppressed(role: str, service: str) -> bool:
    """Whether the service entry carries ``# nocheck: image-healthcheck``.

    For a container that genuinely cannot be probed - no shell, no port, a
    one-shot process that exits - the marker records that as a decision rather
    than leaving the gap to look like an oversight.
    """
    path = PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES
    lines = read_text(path).splitlines()
    for number, line in enumerate(lines, start=1):
        if line.startswith(f"{service}:"):
            return is_suppressed_at(lines, number, RULE)
    return False


def is_deployed(role: str, service: str) -> bool:
    """Whether the entry is a service at all.

    ``enabled: false`` marks a mirror-only entry: CI pulls the image, nothing
    ever runs it as a container, so there is no process for a probe to judge.
    """
    services = load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES)
    entry = services.get(service) if isinstance(services, dict) else None
    return not (isinstance(entry, dict) and entry.get("enabled") is False)


def declared_healthcheck(role: str, service: str) -> bool:
    """Whether anything in the repository gives this service a probe.

    Two places count. ``services.<service>.healthcheck`` is the SPOT and is
    attributed exactly. A template may also carry a literal ``healthcheck:``
    block or a ``container_healthcheck`` call - nextcloud spells its
    ``occ status`` probe that way, and every redis sidecar inherits one from
    the included svc-db-redis partial. Those cannot be attributed to a single
    service without rendering the compose file, so a template hit clears the
    whole role. That direction is deliberate: it can let a genuinely bare
    service pass, where the opposite would report a probe that plainly exists.
    """
    services = load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES)
    if isinstance(services, dict):
        entry = services.get(service)
        if isinstance(entry, dict) and entry.get("healthcheck"):
            return True
    return _templates_declare(role)


def _templates_declare(role: str) -> bool:
    """Whether anything the role ships carries a probe.

    Four places produce one: a template's literal block, a
    ``container_healthcheck`` call, a partial the template pulls in through
    ``include`` or ``lookup('template', …)``, and a ``HEALTHCHECK`` line in a
    Dockerfile the role builds its own image from - where the ``image:`` in
    services.yml names only the base.
    """
    prefix = f"roles/{role}/"
    for path_str, text in iter_project_files_with_content(
        extensions=(".j2", ".yml", ".sh", "Dockerfile", "Dockerfile.j2"),
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not rel.startswith(prefix):
            continue
        if HEALTHCHECK_IN_TEMPLATE.search(text):
            return True
        for included in INCLUDED_TEMPLATE.findall(text):
            partial = PROJECT_ROOT / included
            if partial.is_file() and HEALTHCHECK_IN_TEMPLATE.search(read_text(partial)):
                return True
    return False


class TestImageHealthcheckDeclared(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mirror = mirror_image(MIRROR_PROBE)
        if cls.mirror is None:
            message = (
                "no GHCR mirror resolves for "
                f"'{MIRROR_PROBE}'. The mirror is what keeps a sweep of every "
                "declared image inside the anonymous rate limit this address "
                "shares with every other pull, so this test does not fall back "
                "to the upstream registries"
            )
            if in_github_actions():
                raise AssertionError(
                    f"{message}. On CI the prefix is expected: "
                    "utils/env/handlers/gha_passthrough.py passes "
                    "INFINITO_GHCR_MIRROR_PREFIX through, and it is missing"
                )
            raise unittest.SkipTest(
                f"{message}. Locally the prefix is absent by design - "
                "gha_passthrough.py writes it only on CI"
            )
        cls.refs = sorted(
            iter_role_images(PROJECT_ROOT), key=lambda ref: (ref.role, ref.service)
        )
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            cls.probed = list(
                pool.map(
                    lambda ref: image_healthcheck_probed(ref.name, ref.version),
                    cls.refs,
                )
            )

    def test_the_mirror_answered_more_often_than_the_upstream_registries(self) -> None:
        """Reading upstream is the fallback for images the mirror misses; once
        it answers most of the sweep it is the rule, and the rate limit is
        being spent again."""
        sources = Counter(source for _found, source in self.probed)
        self.assertGreater(
            sources["mirror"] + sources["cache"],
            sources["upstream"],
            f"the mirror carried only {sources['mirror']} of {len(self.refs)} "
            f"image(s) while {sources['upstream']} came from upstream: {sources}",
        )

    def test_every_image_without_an_onboard_probe_declares_one(self) -> None:
        missing = []
        indeterminate = []
        onboard = 0
        for ref, (found, _source) in zip(self.refs, self.probed, strict=True):
            if found is None:
                indeterminate.append(f"{ref.role}:{ref.service} ({ref.source})")
            elif found:
                onboard += 1
            elif not is_deployed(ref.role, ref.service) or is_suppressed(
                ref.role, ref.service
            ):
                continue
            elif not declared_healthcheck(ref.role, ref.service):
                missing.append(f"{ref.role}:{ref.service} ({ref.source})")

        print(
            f"\n{len(self.refs)} image(s): {onboard} ship a probe, "
            f"{len(indeterminate)} unreachable, {len(missing)} without one"
        )
        self.assertEqual(
            missing,
            [],
            "these images declare no HEALTHCHECK and their role declares none "
            "either, so nothing can tell whether the container actually "
            f"serves. Declare a probe, or mark the entry '# nocheck: {RULE}' "
            "where none is possible:\n  " + "\n  ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()

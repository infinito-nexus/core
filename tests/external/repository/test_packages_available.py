"""External: every declared package resolves in its distribution's index.

Queries the official package index of each default distribution in
parallel instead of installing anything, so the whole registry is checked
in seconds rather than one container build per package.

A package that the index positively reports as absent fails the test. A
network or index error is reported as a warning, because an unreachable
mirror says nothing about the declaration.
"""

from __future__ import annotations

import concurrent.futures
import unittest
import warnings

from utils.packages.registry import build_registry, resolve
from utils.packages.schema import DISTRO_FAMILY

from . import PROJECT_ROOT
from ._package_probes import (
    _MAX_WORKERS,
    Outcome,
    PackageAvailabilityWarning,
    Probe,
    _probe,
)


def _collect_probes() -> list[Probe]:
    probes: list[Probe] = []
    for package_id, declaration in sorted(build_registry(PROJECT_ROOT).items()):
        for distro in sorted(DISTRO_FAMILY):
            spec = resolve(declaration, distro)
            if spec is None:
                continue
            probes.extend(
                Probe(
                    package_id,
                    distro,
                    name,
                    spec.repo,
                    spec.source,
                    spec.virtual,
                )
                for name in spec.names
            )
    return probes


class TestPackagesAvailable(unittest.TestCase):
    def test_declared_packages_exist_in_their_index(self) -> None:
        probes = _collect_probes()
        if not probes:
            self.skipTest("no packages declared")

        outcomes: list[Outcome] = []
        with concurrent.futures.ThreadPoolExecutor(_MAX_WORKERS) as pool:
            outcomes.extend(pool.map(_probe, probes))

        unknown = [o for o in outcomes if o.available is None]
        for outcome in (o for o in unknown if o.declared):
            warnings.warn(
                f"{outcome.probe.package_id} / {outcome.probe.distro} / "
                f"{outcome.probe.name}: {outcome.detail}",
                PackageAvailabilityWarning,
                stacklevel=1,
            )

        unverified = [o for o in unknown if not o.declared]
        if unverified:
            self.fail(
                f"{len(unverified)} package(s) could not be checked at all, so "
                "reporting this run green would claim a verification that did "
                "not happen. Fix the index access, or declare the exemption "
                "(third-party repo / virtual) where the package is declared:\n"
                + "\n".join(
                    f"  - {o.probe.package_id} / {o.probe.distro} / "
                    f"{o.probe.name}: {o.detail}"
                    for o in sorted(
                        unverified, key=lambda o: (o.probe.package_id, o.probe.distro)
                    )
                )
            )

        missing = [o for o in outcomes if o.available is False]
        if not missing:
            return

        lines = [
            (
                f"{len(missing)} declared package(s) were not found in the index "
                f"of their distribution (probed {len(probes)}, "
                f"{len(unknown)} inconclusive):"
            )
        ]
        lines.extend(
            f"  - {outcome.probe.package_id} / {outcome.probe.distro}: "
            f"'{outcome.probe.name}' absent from {outcome.detail}"
            for outcome in sorted(
                missing, key=lambda o: (o.probe.package_id, o.probe.distro)
            )
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()

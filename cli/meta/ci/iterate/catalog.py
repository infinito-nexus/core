"""The facts the plan reads off the roles tree, behind one seam so tests can
hand in their own: the role universe, the variant rows CI tests, the closure
the affected resolver computes, a row's include set and what it declares.

Every fact comes from the module the deploy itself uses, so the plan cannot
drift from it: the closure from ``cli.meta.roles.applications.resolution
.affected`` (the resolver ``affected_roles.sh`` calls), the rows from the
complexity model the matrix planner reads, the include set from
``cli.meta.ci.host_rows.swarm_closure``, the storage from
``utils.storage.constrained`` and the free space from
``cli.meta.ci.swarm_preflight.free_space``.
"""

from __future__ import annotations

import io
import os
from contextlib import contextmanager, redirect_stderr
from functools import cached_property
from typing import TYPE_CHECKING, NamedTuple

from cli.meta.ci.host_rows import ROLES_DIR, round_variants, swarm_closure
from cli.meta.ci.swarm_preflight import free_space
from cli.meta.roles.applications.complexity.model import (
    compute_complexity_rows,
    compute_variant_complexity_rows,
)
from cli.meta.roles.applications.resolution.affected.__main__ import (
    affected_selection,
)
from utils.cache.applications import get_variants
from utils.cache.files import PROJECT_ROOT
from utils.github.variant import network
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    canonical_service_key,
)
from utils.storage.constrained import closure_storage, required_storage_bytes

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from cli.meta.ci.host_rows import Closure

UNIT_LANGUAGES = ("python", "javascript", "php", "ruby")


class Row(NamedTuple):
    """One variant of an application role, as CI tests it.

    Attributes:
        app: the application id.
        variant: the variant index.
        embeds: how many providers the row pulls in transitively, the first
            cheapness rank of the row.
        weight: the complexity weight, the second rank.
        compose: CI deploys the row in compose.
        swarm: CI deploys the row in swarm.
        host: CI deploys the row onto a host, a mode no local loop runs.
        variants: how many variants the role declares.
    """

    app: str
    variant: int
    embeds: int
    weight: int
    compose: bool
    swarm: bool
    host: bool
    variants: int


@contextmanager
def _disabled(keys: Iterable[str]) -> Iterator[None]:
    previous = os.environ.get("disable")
    os.environ["disable"] = ",".join(keys)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("disable", None)
        else:
            os.environ["disable"] = previous


class Catalog:
    """The real facts of this checkout's roles tree, each read once."""

    @cached_property
    def roles(self) -> tuple[str, ...]:
        return tuple(sorted(p.name for p in ROLES_DIR.iterdir() if p.is_dir()))

    @cached_property
    def _rows(self) -> dict[str, tuple[Row, ...]]:
        grouped: dict[str, list[Row]] = {}
        for row in compute_variant_complexity_rows(ROLES_DIR):
            grouped.setdefault(row.name, []).append(
                Row(
                    row.name,
                    row.variant or 0,
                    row.embeds,
                    row.weight,
                    row.test_compose,
                    row.test_swarm,
                    row.test_host,
                    0,
                )
            )
        return {
            app: tuple(row._replace(variants=len(rows)) for row in rows)
            for app, rows in grouped.items()
        }

    def rows(self, app: str) -> tuple[Row, ...]:
        """Return every variant row of *app*, empty for a role without one."""
        return self._rows.get(app, ())

    @cached_property
    def representatives(self) -> tuple[str, ...]:
        """One role per base cluster, heaviest first: the default set of
        ``make roundtrip``."""
        rows = [row for row in compute_complexity_rows(ROLES_DIR) if not row.clone]
        return tuple(r.name for r in sorted(rows, key=lambda r: (-r.weight, r.name)))

    @cached_property
    def _affected(self) -> dict[tuple[str, ...], tuple[list[str], str]]:
        return {}

    def affected(self, seeds: Iterable[str]) -> tuple[list[str], str]:
        """Return the selection tokens the seeds reach, and why the resolver
        refused them (empty when it did not)."""
        wanted = tuple(sorted(set(seeds)))
        if not wanted:
            return [], ""
        if wanted not in self._affected:
            stderr = io.StringIO()
            try:
                with redirect_stderr(stderr):
                    self._affected[wanted] = (affected_selection(wanted), "")
            except SystemExit as exc:
                told = stderr.getvalue().strip() or str(exc.code)
                refused = f"the affected resolver refused {list(wanted)}: {told}"
                self._affected[wanted] = ([], refused)
        return self._affected[wanted]

    @cached_property
    def _closures(self) -> dict[tuple[str, int, tuple[str, ...]], Closure]:
        return {}

    def closure(self, app: str, variant: int, disable: Iterable[str]) -> Closure:
        """Return the include set the swarm provision step derives for a row,
        pruned by *disable* the way the provision step prunes it."""
        key = (app, variant, tuple(disable))
        if key not in self._closures:
            with _disabled(key[2]):
                self._closures[key] = swarm_closure(app, variant)
        return self._closures[key]

    @cached_property
    def _measure(self):
        return closure_storage(ROLES_DIR)

    def declared(self, closure: Closure) -> dict[str, int]:
        """Return the min_storage each role of an include set declares."""
        return self._measure(closure.roles, closure.variants)

    def compose_declared(self, app: str, variant: int) -> int:
        """Return the min_storage a compose deploy of the row declares, the
        figure ``STORAGE_CONSTRAINED`` compares.

        Raises:
            SystemExit: the app declares no such variant.
        """
        return required_storage_bytes([app], round_variants(app, variant))

    def free_bytes(self) -> int:
        """Return the free space a deploy can grow into.

        Raises:
            RuntimeError: the Docker daemon cannot be asked.
        """
        return free_space()

    @cached_property
    def _registry(self) -> dict:
        return build_service_registry_from_roles_dir(ROLES_DIR)

    def provider(self, key: str) -> str:
        """Return the role providing a service key, empty when none does."""
        primary = canonical_service_key(self._registry, key)
        role = (self._registry.get(primary) or {}).get("role")
        return role if isinstance(role, str) else ""

    @cached_property
    def _variants(self) -> dict:
        return get_variants(roles_dir=str(ROLES_DIR), readonly=True)

    def networks(self, app: str, variant: int, closure: Closure) -> tuple[str, ...]:
        """Return the node network modes the row can be served in."""
        return network.row_states(
            app,
            variant,
            self._variants,
            pulls_tor=network.tor_provider() in closure.roles,
        )

    def unit_tests(self, role: str) -> list[str]:
        """Return the unit test directories of a role, one per language."""
        return [
            f"tests/unit/{language}/roles/{role}"
            for language in UNIT_LANGUAGES
            if (PROJECT_ROOT / "tests" / "unit" / language / "roles" / role).is_dir()
        ]

    def exists(self, path: str) -> bool:
        """Return whether a repository-relative path exists in this checkout."""
        return (PROJECT_ROOT / path).exists()

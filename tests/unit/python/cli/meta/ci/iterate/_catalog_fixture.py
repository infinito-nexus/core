"""A hand-built roles tree for the plan tests: what the real catalog answers,
for a handful of invented roles whose shape every test can read off this file.

``web-app-light`` and ``web-app-heavy`` are two apps on one provider,
``svc-db-store``, which has no row of its own; ``web-app-multi`` has two
variants of which only the second reaches the provider; ``dsk-tool`` is tested
on a host only. ``web-app-matomo`` provides the ``matomo`` key.
"""

from __future__ import annotations

from typing import NamedTuple

from cli.meta.ci.iterate.catalog import Row

ROLES = (
    "dsk-tool",
    "svc-db-store",
    "web-app-heavy",
    "web-app-light",
    "web-app-matomo",
    "web-app-multi",
)
ROWS = {
    "web-app-light": (Row("web-app-light", 0, 2, 4, True, True, False, 1),),
    "web-app-heavy": (Row("web-app-heavy", 0, 9, 20, True, True, False, 1),),
    "web-app-multi": (
        Row("web-app-multi", 0, 1, 3, True, True, False, 2),
        Row("web-app-multi", 1, 5, 8, True, False, False, 2),
    ),
    "web-app-matomo": (Row("web-app-matomo", 0, 3, 6, True, True, False, 1),),
    "dsk-tool": (Row("dsk-tool", 0, 1, 1, False, False, True, 1),),
}
CLOSURE = {
    "svc-db-store": [
        "svc-db-store",
        "web-app-heavy",
        "web-app-light",
        "web-app-multi#1",
    ],
    "web-app-light": ["web-app-light"],
    "web-app-heavy": ["web-app-heavy"],
    "web-app-multi": ["web-app-multi"],
    "web-app-matomo": ["web-app-heavy", "web-app-matomo"],
    "dsk-tool": ["dsk-tool"],
}
GIB = 2**30


class FakeClosure(NamedTuple):
    roles: tuple[str, ...]
    variants: dict[str, int]


class FakeCatalog:
    """Answers like :class:`cli.meta.ci.iterate.catalog.Catalog` for :data:`ROLES`.

    Attributes:
        free: the free bytes to report; None makes the daemon unreachable.
        refuse: seeds the resolver refuses, as it refuses a non-modellable one.
    """

    roles = ROLES
    representatives = ("web-app-heavy", "web-app-light")
    free: int | None = 100 * GIB
    refuse: frozenset[str] = frozenset()

    def rows(self, app: str) -> tuple[Row, ...]:
        return ROWS.get(app, ())

    def affected(self, seeds) -> tuple[list[str], str]:
        wanted = tuple(sorted(set(seeds)))
        if not wanted:
            return [], ""
        if self.refuse & set(wanted):
            return [], f"refused {sorted(self.refuse & set(wanted))}"
        tokens: dict[str, str] = {}
        for seed in wanted:
            for token in CLOSURE[seed]:
                app = token.partition("#")[0]
                tokens[app] = app if app in wanted else tokens.get(app, token)
        return sorted(tokens.values()), ""

    def closure(self, app: str, variant: int, disable) -> FakeClosure:
        return FakeClosure((app, "svc-db-store"), {app: variant})

    def declared(self, closure: FakeClosure) -> dict[str, int]:
        return dict.fromkeys(closure.roles, GIB)

    def compose_declared(self, app: str, variant: int) -> int:
        return 3 * GIB

    def free_bytes(self) -> int:
        if self.free is None:
            raise RuntimeError("cannot determine Docker's data root")
        return self.free

    def provider(self, key: str) -> str:
        return {"matomo": "web-app-matomo"}.get(key, "")

    def networks(self, app: str, variant: int, closure: FakeClosure) -> tuple[str, ...]:
        return ("clearnet", "multi") if app != "web-app-heavy" else ("clearnet",)

    def unit_tests(self, role: str) -> list[str]:
        return [f"tests/unit/python/roles/{role}"] if role == "web-app-light" else []

    def exists(self, path: str) -> bool:
        return not path.startswith("gone/")

# cli/meta/applications/resolution/combined/resolver.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from .role_introspection import (
    load_dependencies_app_only,
    load_run_after,
    load_shared_service_roles_for_app,
    require_role_exists,
)


@dataclass(frozen=True)
class RoleEdges:
    run_after: List[str]
    dependencies: List[str]
    services: List[str]


class CombinedResolver:
    """
    Resolve a combined prerequisite graph:
      prerequisites(role) = run_after(role) + dependencies(role) + services(role)

    Notes:
    - run_after edges are always followed
    - dependency edges are followed only for application roles (filtered in loader)
    - services edges are derived from app config flags (filtered in loader)
    - Cycles do NOT raise; traversal stops expanding the cyclic edge
      (tree output shows cycles separately via stack detection).

    When `services_overrides` is provided, services edges for each role
    in the dict are derived from the override map instead of the role's
    on-disk `meta/services.yml`. Callers use this to feed in the
    variant-merged services map per round so the resolver sees the same
    topology the inventory will bake. A `CombinedResolver` instance is
    therefore round-specific: do NOT reuse one across rounds.
    """

    def __init__(
        self,
        services_overrides: Dict[str, dict] | None = None,
    ) -> None:
        self._cache: Dict[str, RoleEdges] = {}
        self._services_overrides: Dict[str, dict] = dict(services_overrides or {})

    def edges_for(self, role_name: str) -> RoleEdges:
        if role_name in self._cache:
            return self._cache[role_name]

        require_role_exists(role_name)

        ra = load_run_after(role_name)
        deps = load_dependencies_app_only(role_name)
        svcs = load_shared_service_roles_for_app(
            role_name,
            services_override=self._services_overrides.get(role_name),
        )

        # Validate referenced roles exist for run_after (deps/services validate internally too)
        for r in ra:
            require_role_exists(r)

        edges = RoleEdges(run_after=ra, dependencies=deps, services=svcs)
        self._cache[role_name] = edges
        return edges

    def resolve(self, start_role: str) -> List[str]:
        """
        Return prerequisites-first (post-order) list, excluding start_role.

        Cycle tolerant:
        - If a node is already on the current stack, stop expanding that edge.
        """
        require_role_exists(start_role)

        visited: Set[str] = set()
        stack: List[str] = []
        out: List[str] = []

        def dfs(node: str) -> None:
            if node in stack:
                # cycle edge -> stop expansion, do not raise
                return
            if node in visited:
                return

            visited.add(node)
            stack.append(node)

            edges = self.edges_for(node)

            # Keep stable traversal order
            for dep in edges.run_after:
                dfs(dep)
            for dep in edges.dependencies:
                dfs(dep)
            for dep in edges.services:
                dfs(dep)

            stack.pop()

            if node != start_role:
                out.append(node)

        dfs(start_role)
        return out

    def resolve_with_edges(
        self, start_role: str
    ) -> Tuple[List[str], Dict[str, RoleEdges]]:
        resolved = self.resolve(start_role)
        return resolved, dict(self._cache)

"""Performance smoke tests for runtime_data caching.

These simulate the Ansible-in-a-play calling pattern that dominates deploy time:
many tasks each receive a fresh `variables` mapping (per-task get_vars() churn)
but reuse the same underlying inventory dicts by reference. If the merged-payload
caches miss across tasks, every `lookup('applications')` / `lookup('service', …)`
call re-renders the full applications tree and deploys slow to a crawl.
"""

from __future__ import annotations

import time
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.applications import (
    LookupModule as ApplicationsLookup,
)
from plugins.lookup.applications import (
    _reset_cache_for_tests,
)
from plugins.lookup.applications_current_play import (
    LookupModule as ApplicationsCurrentPlayLookup,
)
from plugins.lookup.applications_current_play import (
    _reset_cache_for_tests as _reset_current_play_cache,
)
from plugins.lookup.domains import (
    LookupModule as DomainsLookup,
)
from plugins.lookup.domains import (
    _reset_cache_for_tests as _reset_domains_cache,
)

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


def _simulate_ansible_variables(
    shared_applications: dict,
    shared_users: dict,
) -> dict:
    """Build a fresh per-task `variables` mapping.

    Ansible 2.19+ VariableManager.get_vars() returns a new top-level mapping for
    every task, but inventory-level sub-objects (applications, users) are reused
    by reference unless a `set_fact` replaces them.
    """
    return {
        "applications": shared_applications,
        "users": shared_users,
        "DOMAIN_PRIMARY": "infinito.example",
        "SYSTEM_EMAIL_DOMAIN": "infinito.example",
        "group_names": [],
    }


class TestRuntimeLookupPerformance(unittest.TestCase):
    ITERATIONS = 200
    WARM_CALLS_BUDGET_SECONDS = 0.5

    def setUp(self) -> None:
        _reset_cache_for_tests()
        _reset_current_play_cache()
        _reset_domains_cache()
        self.shared_applications: dict = {}
        self.shared_users: dict = {}

    def tearDown(self) -> None:
        _reset_cache_for_tests()
        _reset_current_play_cache()
        _reset_domains_cache()

    def _call_applications(self, variables: dict) -> None:
        lookup = ApplicationsLookup()
        lookup._templar = Templar(loader=DataLoader())
        lookup.run([], variables=variables, roles_dir=str(ROLES_DIR))

    def _call_applications_current_play(self, variables: dict) -> None:
        lookup = ApplicationsCurrentPlayLookup()
        lookup._templar = Templar(loader=DataLoader())
        lookup.run([], variables=variables, roles_dir=str(ROLES_DIR))

    def _call_domains(self, variables: dict) -> None:
        lookup = DomainsLookup()
        lookup._templar = Templar(loader=DataLoader())
        lookup.run([], variables=variables, roles_dir=str(ROLES_DIR))

    def test_applications_lookup_caches_across_fresh_variables_dicts(self) -> None:
        """Warm call populates the cache; subsequent calls with freshly-built
        `variables` mappings AND freshly-copied applications/users dicts
        (Ansible 2.19+ VariableManager behavior) must hit the cache and stay
        under budget.

        Using a single for-loop here is test-code-only and not production code
        generating files/tasks; the CLAUDE.md shell-loop ban does not apply.
        """
        warm = _simulate_ansible_variables(self.shared_applications, self.shared_users)
        t0 = time.perf_counter()
        self._call_applications(warm)
        warm_elapsed = time.perf_counter() - t0

        import copy

        t0 = time.perf_counter()
        for _ in range(self.ITERATIONS):
            # Ansible 2.19+ may churn the inventory-level sub-dicts per task
            # too; deep-copy each iteration to detect id()-only cache bugs.
            variables = _simulate_ansible_variables(
                copy.deepcopy(self.shared_applications),
                copy.deepcopy(self.shared_users),
            )
            self._call_applications(variables)
        hot_elapsed = time.perf_counter() - t0

        avg_ms = hot_elapsed / self.ITERATIONS * 1000
        warm_over_hot_avg = (warm_elapsed * 1000) / max(avg_ms, 0.001)

        self.assertLess(
            hot_elapsed,
            self.WARM_CALLS_BUDGET_SECONDS,
            f"{self.ITERATIONS} cached lookups took {hot_elapsed:.2f}s "
            f"(avg {avg_ms:.2f}ms). Budget: {self.WARM_CALLS_BUDGET_SECONDS}s. "
            f"Warm-up: {warm_elapsed:.2f}s ({warm_over_hot_avg:.0f}x avg hot).",
        )
        self.assertGreater(
            warm_over_hot_avg,
            50.0,
            f"Cache not providing meaningful speed-up: warm={warm_elapsed:.2f}s "
            f"vs avg hot={avg_ms:.2f}ms (ratio {warm_over_hot_avg:.1f}x). "
            "Expected cache hits to be >=50x faster than cold render.",
        )

    def test_applications_lookup_warmup_budget(self) -> None:
        """First render on full roles/ dir must complete in reasonable time."""
        variables = _simulate_ansible_variables(
            self.shared_applications, self.shared_users
        )
        t0 = time.perf_counter()
        self._call_applications(variables)
        warm_elapsed = time.perf_counter() - t0

        self.assertLess(
            warm_elapsed,
            120.0,
            f"Cold applications render took {warm_elapsed:.2f}s (budget 120s).",
        )

    def test_applications_current_play_lookup_caches(self) -> None:
        """applications_current_play must also cache across per-task churn.

        The Merge tasks in tasks/stages/01_constructor.yml call this lookup
        many times (once for CURRENT_PLAY_APPLICATIONS, plus transitively via
        filters). Without caching, each call rebuilds the service registry and
        walks the dep graph — expensive on a full roles/ tree.
        """
        warm = _simulate_ansible_variables(self.shared_applications, self.shared_users)
        t0 = time.perf_counter()
        self._call_applications_current_play(warm)
        warm_elapsed = time.perf_counter() - t0

        import copy

        t0 = time.perf_counter()
        for _ in range(self.ITERATIONS):
            variables = _simulate_ansible_variables(
                copy.deepcopy(self.shared_applications),
                copy.deepcopy(self.shared_users),
            )
            self._call_applications_current_play(variables)
        hot_elapsed = time.perf_counter() - t0

        avg_ms = hot_elapsed / self.ITERATIONS * 1000
        warm_over_hot_avg = (warm_elapsed * 1000) / max(avg_ms, 0.001)

        self.assertLess(
            hot_elapsed,
            self.WARM_CALLS_BUDGET_SECONDS,
            f"{self.ITERATIONS} cached applications_current_play lookups took "
            f"{hot_elapsed:.2f}s (avg {avg_ms:.2f}ms). "
            f"Budget: {self.WARM_CALLS_BUDGET_SECONDS}s.",
        )
        self.assertGreater(
            warm_over_hot_avg,
            50.0,
            f"applications_current_play cache not providing meaningful speed-up: "
            f"warm={warm_elapsed:.2f}s vs avg hot={avg_ms:.2f}ms "
            f"(ratio {warm_over_hot_avg:.1f}x).",
        )

    def test_domains_lookup_caches_across_fresh_variables_dicts(self) -> None:
        """Warm call populates the domains cache; subsequent calls with freshly-
        built `variables` mappings AND freshly-copied applications/users dicts
        must hit the cache and stay under budget.

        Same guarantees as test_applications_lookup_caches_across_fresh_variables_dicts,
        but for lookup('domains'). Without caching, each call re-runs
        canonical_domains_map over the full roles/ tree.
        """
        warm = _simulate_ansible_variables(self.shared_applications, self.shared_users)
        t0 = time.perf_counter()
        self._call_domains(warm)
        warm_elapsed = time.perf_counter() - t0

        import copy

        t0 = time.perf_counter()
        for _ in range(self.ITERATIONS):
            variables = _simulate_ansible_variables(
                copy.deepcopy(self.shared_applications),
                copy.deepcopy(self.shared_users),
            )
            self._call_domains(variables)
        hot_elapsed = time.perf_counter() - t0

        avg_ms = hot_elapsed / self.ITERATIONS * 1000
        warm_over_hot_avg = (warm_elapsed * 1000) / max(avg_ms, 0.001)

        self.assertLess(
            hot_elapsed,
            self.WARM_CALLS_BUDGET_SECONDS,
            f"{self.ITERATIONS} cached domains lookups took {hot_elapsed:.2f}s "
            f"(avg {avg_ms:.2f}ms). Budget: {self.WARM_CALLS_BUDGET_SECONDS}s. "
            f"Warm-up: {warm_elapsed:.2f}s ({warm_over_hot_avg:.0f}x avg hot).",
        )
        self.assertGreater(
            warm_over_hot_avg,
            50.0,
            f"Domains cache not providing meaningful speed-up: warm={warm_elapsed:.2f}s "
            f"vs avg hot={avg_ms:.2f}ms (ratio {warm_over_hot_avg:.1f}x). "
            "Expected cache hits to be >=50x faster than cold render.",
        )

    def test_domains_lookup_warmup_budget(self) -> None:
        """First render of lookup('domains') on full roles/ dir must complete
        in reasonable time."""
        variables = _simulate_ansible_variables(
            self.shared_applications, self.shared_users
        )
        t0 = time.perf_counter()
        self._call_domains(variables)
        warm_elapsed = time.perf_counter() - t0

        self.assertLess(
            warm_elapsed,
            120.0,
            f"Cold domains render took {warm_elapsed:.2f}s (budget 120s).",
        )


if __name__ == "__main__":
    unittest.main()

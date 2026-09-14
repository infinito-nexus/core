"""The `resource` lookup measures and computes every host-resource constant.

Ansible's Linux hardware collector reads `/sys/block/<dev>/size` without a None
guard, and that read runs before the CPU facts in the same collector, so one
unreadable block device drops every hardware fact at once and without a warning.
Templates that dereferenced `processor_vcpus` or `memtotal_mb` died on the first
render.

These tests pin the three properties that make the replacement safe: the values
resolve with no hardware facts at all, the arithmetic matches the Jinja it
replaces, and nothing is ever substituted for a value that could not be
measured.
"""

from __future__ import annotations

import unittest
from typing import ClassVar
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.resource import LookupModule
from utils.cache.errors import UnresolvableValueError

_CPUS = 12
_MEM_MB = 64000


def _vars(**overrides):
    """A play scope whose hardware collector died: facts present, none of them hardware."""
    scope = {
        "ansible_facts": {"os_family": "Debian", "service_mgr": "systemd"},
        "ansible_connection": "local",
        "inventory_hostname": "test-host",
        "applications": {},
        "group_names": [],
    }
    scope.update(overrides)
    return scope


def _run(terms, variables=None, **kwargs):
    lookup = LookupModule()
    lookup._templar = None
    with patch("plugins.lookup.resource.os.cpu_count", return_value=_CPUS), patch(
        "plugins.lookup.resource.mem_total_mb", return_value=_MEM_MB
    ):
        return lookup.run(terms, variables=variables or _vars(), **kwargs)


class TestResourceMeasurement(unittest.TestCase):
    def test_resolves_without_any_hardware_fact(self) -> None:
        self.assertEqual(_run(["host_cpus", "host_mem_mb"]), [_CPUS, _MEM_MB])

    def test_hardware_facts_win_over_the_local_probe(self) -> None:
        scope = _vars(
            ansible_facts={"processor_vcpus": 4, "memtotal_mb": 8000},
        )
        self.assertEqual(_run(["host_cpus", "host_mem_mb"], scope), [4, 8000])

    def test_inventory_override_wins_over_the_facts(self) -> None:
        scope = _vars(
            ansible_facts={"processor_vcpus": 4, "memtotal_mb": 8000},
            RESOURCE_HOST_CPUS_OVERRIDE=7,
            RESOURCE_HOST_MEM_MB_OVERRIDE=1234,
        )
        self.assertEqual(_run(["host_cpus", "host_mem_mb"], scope), [7, 1234])

    def test_a_remote_host_without_facts_raises_instead_of_probing(self) -> None:
        scope = _vars(ansible_connection="ssh", inventory_hostname="remote-box")
        with self.assertRaises(UnresolvableValueError) as caught:
            _run(["host_cpus"], scope)
        message = str(caught.exception)
        self.assertIn("remote-box", message)
        self.assertIn("RESOURCE_HOST_CPUS_OVERRIDE", message)

    def test_a_remote_host_with_an_override_resolves(self) -> None:
        scope = _vars(
            ansible_connection="ssh",
            RESOURCE_HOST_CPUS_OVERRIDE=3,
            RESOURCE_HOST_MEM_MB_OVERRIDE=2048,
        )
        self.assertEqual(_run(["host_cpus", "host_mem_mb"], scope), [3, 2048])

    def test_an_unusable_probe_raises(self) -> None:
        lookup = LookupModule()
        lookup._templar = None
        with patch(
            "plugins.lookup.resource.os.cpu_count", return_value=0
        ), self.assertRaises(UnresolvableValueError) as caught:
            lookup.run(["host_cpus"], variables=_vars())
        self.assertIn("RESOURCE_HOST_CPUS_OVERRIDE", str(caught.exception))

    def test_a_zero_override_is_rejected_rather_than_used(self) -> None:
        scope = _vars(ansible_connection="ssh", RESOURCE_HOST_CPUS_OVERRIDE=0)
        with self.assertRaises(UnresolvableValueError):
            _run(["host_cpus"], scope)

    def test_a_hostless_render_fails_softly(self) -> None:
        """Without a host nothing is being deployed, so nothing may be aborted.

        The inventory generator and the lint suite render the whole applications
        payload with no host in scope, and the meta files of nextcloud and
        svc-opt-swapfile sit in that payload. A non-swallowable abort there would
        fail tooling over a value it never reads.
        """
        scope = _vars(ansible_connection="ssh")
        del scope["inventory_hostname"]
        with self.assertRaises(AnsibleError) as caught:
            _run(["host_cpus"], scope)
        self.assertNotIsInstance(
            caught.exception,
            UnresolvableValueError,
            "A hostless render must raise the swallowable class so best-effort "
            "rendering absorbs it, exactly as the missing fact did before.",
        )


class TestResourceArithmetic(unittest.TestCase):
    """Every expected value is the Jinja expression this lookup replaced."""

    def test_host_memory_is_floored_to_whole_gigabytes(self) -> None:
        self.assertEqual(_run(["host_mem"]), [_MEM_MB // 1024])

    def test_available_resources_subtract_the_reserve(self) -> None:
        self.assertEqual(
            _run(["avail_cpus", "avail_mem"]),
            [_CPUS - 2, (_MEM_MB // 1024) - 4],
        )

    def test_per_container_shares_divide_by_the_active_count(self) -> None:
        avail_cpus = _CPUS - 2
        avail_mem = (_MEM_MB // 1024) - 4
        self.assertEqual(
            _run(["cpus", "mem_reservation", "mem_limit"]),
            [
                max(round(avail_cpus / 1, 2), 0.5),
                f"{round(avail_mem / 1 * 0.7, 1)}g",
                f"{round(avail_mem / 1 * 1.0, 1)}g",
            ],
        )

    def test_a_cpu_share_never_falls_below_the_floor(self) -> None:
        scope = _vars(RESOURCE_HOST_CPUS_OVERRIDE=2)
        self.assertEqual(_run(["cpus"], scope), [0.5])

    def test_postgres_connections_cap_at_four_hundred(self) -> None:
        self.assertEqual(
            _run(["postgres_max_connections"]), [min(_CPUS * 30 + 50, 400)]
        )

    def test_postgres_memory_matches_the_replaced_expressions(self) -> None:
        max_connections = min(_CPUS * 30 + 50, 400)
        self.assertEqual(
            _run(
                [
                    "postgres_shared_buffers",
                    "postgres_work_mem",
                    "postgres_maintenance_work_mem",
                ]
            ),
            [
                f"{_MEM_MB * 25 // 100}MB",
                f"{max(_MEM_MB // max(max_connections, 1) // 2, 1)}MB",
                f"{max(_MEM_MB * 5 // 100, 64)}MB",
            ],
        )

    def test_rounding_goes_half_up_like_jinja(self) -> None:
        from plugins.lookup.resource import _round_half_up

        self.assertEqual(_round_half_up(0.125, 2), 0.13)
        self.assertEqual(_round_half_up(2.5, 0), 3.0)


class TestResourceApplicationsAccess(unittest.TestCase):
    """`applications` is read only for the keys that divide by the container count.

    The meta files of web-app-nextcloud and svc-opt-swapfile read their memory
    back out of this lookup while the applications payload is being rendered.
    Touching `applications` for those keys would make that render re-enter
    itself.
    """

    class _Tripwire(dict):
        def __init__(self):
            super().__init__()
            self.read = False

        def __getitem__(self, key):
            if key == "applications":
                self.read = True
            return super().__getitem__(key)

        def get(self, key, default=None):
            if key == "applications":
                self.read = True
            return super().get(key, default)

    def _scope(self):
        scope = self._Tripwire()
        scope.update(_vars())
        return scope

    def test_host_and_postgres_keys_never_read_applications(self) -> None:
        for key in (
            "host_cpus",
            "host_mem_mb",
            "postgres_max_connections",
            "postgres_shared_buffers",
            "pids_limit",
        ):
            with self.subTest(key=key):
                scope = self._scope()
                _run([key], scope)
                self.assertFalse(
                    scope.read,
                    f"'{key}' read 'applications'. That re-enters the "
                    f"applications render, which is what reads this key.",
                )

    def test_share_keys_do_read_applications(self) -> None:
        scope = self._scope()
        _run(["cpus"], scope)
        self.assertTrue(
            scope.read,
            "'cpus' divides by the active container count, so it must read "
            "'applications'; a silent 1 would size every container wrong.",
        )


class TestUnresolvableSurvivesBestEffortRender(unittest.TestCase):
    """A best-effort render must not turn "cannot measure" into an empty value.

    `utils.cache.base._render_with_templar` and the two templar helpers behind
    it swallow every exception so a meta payload can render in rounds. The meta
    files of web-app-nextcloud and svc-opt-swapfile read their memory through
    this lookup, so without an exemption the abort would be silently absorbed
    exactly where the wrong number does the most damage.
    """

    def test_the_render_helpers_re_raise_it(self) -> None:
        from utils.cache.base import _render_with_templar

        class _ExplodingTemplar:
            available_variables: ClassVar[dict] = {}

            def template(self, *_args, **_kwargs):
                raise UnresolvableValueError("resource: cannot determine the host CPUs")

        with self.assertRaises(UnresolvableValueError):
            _render_with_templar(
                "{{ lookup('resource', 'host_cpus') }}",
                templar=_ExplodingTemplar(),
                variables={},
            )

    def test_an_ordinary_failure_is_still_swallowed(self) -> None:
        from utils.cache.base import _render_with_templar

        class _ExplodingTemplar:
            available_variables: ClassVar[dict] = {}

            def template(self, *_args, **_kwargs):
                raise ValueError("some expression that cannot resolve yet")

        try:
            _render_with_templar(
                "{{ SOMETHING_NOT_READY }}",
                templar=_ExplodingTemplar(),
                variables={},
            )
        except Exception as exc:
            self.fail(
                f"A value that merely cannot resolve in this round must be "
                f"absorbed so the next round can retry it. Only an unmeasurable "
                f"host value aborts. Got {exc!r}."
            )

    def test_it_is_found_through_ansibles_wrapper(self) -> None:
        from utils.cache.errors import is_unresolvable

        original = UnresolvableValueError("resource: cannot determine the host CPUs")
        try:
            try:
                raise original
            except UnresolvableValueError as exc:
                raise AnsibleError("The lookup plugin 'resource' failed") from exc
        except AnsibleError as wrapped:
            self.assertTrue(
                is_unresolvable(wrapped),
                "Ansible wraps an exception raised inside a lookup, so the "
                "original is only reachable through the cause chain.",
            )

    def test_an_unrelated_error_is_not_mistaken_for_it(self) -> None:
        from utils.cache.errors import is_unresolvable

        self.assertFalse(is_unresolvable(ValueError("unrelated")))
        self.assertFalse(is_unresolvable(None))


class TestResourceInterface(unittest.TestCase):
    def test_an_unknown_key_names_the_valid_ones(self) -> None:
        with self.assertRaises(AnsibleError) as caught:
            _run(["not_a_resource"])
        message = str(caught.exception)
        self.assertIn("not_a_resource", message)
        self.assertIn("host_cpus", message)

    def test_no_terms_returns_nothing(self) -> None:
        self.assertEqual(_run([]), [])

    def test_a_single_list_term_is_expanded(self) -> None:
        self.assertEqual(_run([["host_cpus", "host_mem_mb"]]), [_CPUS, _MEM_MB])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

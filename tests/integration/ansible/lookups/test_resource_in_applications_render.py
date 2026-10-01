"""The `resource` lookup resolves while the real applications payload renders.

Two meta files read their memory back out of this lookup: web-app-nextcloud
sizes PHP from it and svc-opt-swapfile sizes the swapfile from it. Both are
rendered by `get_merged_applications`, so the lookup runs *inside* that render.

Two ways that can go wrong, and neither shows up against a hand-built scope:

* Reading `applications` from inside the lookup pulls the payload back through
  the templar while it is still being produced, so the render re-enters itself.
* `_render_with_templar` swallows every exception by design, which would turn a
  value that could not be measured into an empty string exactly where a wrong
  memory limit does the most damage.

These tests drive the real loader over the real roles tree with a real templar,
which is the only place both are observable.
"""

from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache import _reset_cache_for_tests
from utils.cache.applications import get_merged_applications
from utils.cache.errors import is_unresolvable

from . import PROJECT_ROOT

_ROLES_DIR = PROJECT_ROOT / "roles"

_NEXTCLOUD = "web-app-nextcloud"
_SWAPFILE = "svc-opt-swapfile"


def _scope(**overrides):
    """A play scope with the hardware collector dead and the target local.

    The group_vars constants are deliberately absent. `_render_with_templar`
    replaces the templar's variables with a flat dict, which drops the lazy
    resolution a play uses to expand a variable that itself holds a lookup. A
    meta file reaching the value through such a variable renders `0` here while
    the same expression yields the real number in a play, so the meta files call
    the lookup directly and this scope proves they do.
    """
    scope = {
        "ansible_facts": {"os_family": "Debian"},
        "ansible_connection": "local",
        "inventory_hostname": "localhost",
        "group_names": [],
        "RESOURCE_HOST_CPUS_OVERRIDE": None,
        "RESOURCE_HOST_MEM_MB_OVERRIDE": None,
    }
    scope.update(overrides)
    return scope


def _render(scope):
    _reset_cache_for_tests()
    return get_merged_applications(
        variables=scope,
        roles_dir=str(_ROLES_DIR),
        templar=Templar(loader=DataLoader()),
    )


class TestResourceInApplicationsRender(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_cache_for_tests()

    def test_the_render_completes_and_sizes_both_consumers(self) -> None:
        applications = _render(_scope(RESOURCE_HOST_MEM_MB_OVERRIDE=64000))

        php = applications[_NEXTCLOUD]["services"]["nextcloud"]["performance"]["php"]
        swapfile = applications[_SWAPFILE]["services"]["swapfile"]

        self.assertEqual(php["memory_limit"], f"{64000 // 30}M")
        self.assertEqual(php["opcache_memory_consumption"], f"{64000 // 30}M")
        self.assertEqual(swapfile["swapfile_size"], "64000M")

    def test_an_unmeasurable_host_aborts_the_render(self) -> None:
        """A remote target with no hardware facts must not render an empty size.

        Ansible wraps the lookup's exception in its own templating error, so the
        assertion is that the abort survives the render at all and that the
        cause chain still identifies it. Matching on the wrapper's type would
        pin an ansible internal instead.
        """
        with self.assertRaises(Exception) as caught:
            _render(_scope(ansible_connection="ssh", inventory_hostname="remote-box"))

        self.assertTrue(
            is_unresolvable(caught.exception),
            f"The abort reached the caller as {type(caught.exception).__name__} "
            f"but the cause chain no longer identifies it, so the render layers "
            f"would swallow it again: {caught.exception}",
        )
        self.assertIn("RESOURCE_HOST_CPUS_OVERRIDE", str(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

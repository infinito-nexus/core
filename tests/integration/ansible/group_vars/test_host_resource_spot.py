"""Host-resource constants come from the `resource` lookup and nowhere else.

Seven expressions across four files used to dereference
`ansible_facts['processor_vcpus']` or `ansible_facts['memtotal_mb']` directly.
One unreadable block device kills Ansible's whole Linux hardware collector, so
all seven died together on the first render.

The arithmetic now lives in `plugins/lookup/resource.py`. These tests hold the
boundary that keeps it a single source: `17_resource.yml` computes nothing of
its own, and no role reads the fragile facts again.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_ROLES = PROJECT_ROOT / "roles"
_GROUP_VARS = PROJECT_ROOT / "group_vars/all/17_resource.yml"
_PLUGIN = PROJECT_ROOT / "plugins/lookup/resource.py"

_FRAGILE_FACTS = ("processor_vcpus", "memtotal_mb")

_CONSUMERS = (
    _ROLES / "svc-opt-swapfile" / ROLE_FILE_META_SERVICES,
    _ROLES / "web-app-nextcloud" / ROLE_FILE_META_SERVICES,
    _ROLES / "svc-runner" / ROLE_FILE_DEFAULTS_MAIN,
)

_OVERRIDE_KEYS = ("RESOURCE_HOST_CPUS_OVERRIDE", "RESOURCE_HOST_MEM_MB_OVERRIDE")

_PYTHON_READ_KEYS = ("TIMEOUT_FACTOR",)

_LOOKUP_CALL = re.compile(r"^\{\{\s*lookup\(\s*['\"]resource['\"]\s*,.*\)\s*\}\}$")


def _group_vars() -> dict:
    return load_yaml_any(str(_GROUP_VARS)) or {}


class TestHostResourceSpot(unittest.TestCase):
    def test_every_constant_is_produced_by_the_lookup(self) -> None:
        exempt = (*_OVERRIDE_KEYS, *_PYTHON_READ_KEYS)
        offenders = {
            name: value
            for name, value in _group_vars().items()
            if name not in exempt and not _LOOKUP_CALL.match(str(value).strip())
        }
        self.assertEqual(
            offenders,
            {},
            f"{_GROUP_VARS} must set every constant through "
            f"lookup('resource', '<key>'). Arithmetic here is a second place "
            f"the sizing can drift from the plugin. Found {offenders}.",
        )

    def test_a_constant_read_from_python_stays_a_literal(self) -> None:
        """A plugin reading a constant off `variables` sees it unrendered.

        `plugins/lookup/timeout.py` takes `TIMEOUT_FACTOR` straight from the
        play variables, where a plain dict read returns whatever string the
        group_var holds. Routing such a constant through a lookup hands that
        plugin `"{{ lookup(...) }}"` instead of a number, and the play dies on
        the first task that scales a timeout.
        """
        group_vars = _group_vars()
        for name in _PYTHON_READ_KEYS:
            with self.subTest(constant=name):
                value = group_vars.get(name)
                self.assertIsInstance(
                    value,
                    (int, float),
                    f"{name} is read from Python, which never renders Jinja, so "
                    f"it MUST stay a literal number. Found {value!r}.",
                )

    def test_the_overrides_stay_declared_and_unset(self) -> None:
        group_vars = _group_vars()
        for key in _OVERRIDE_KEYS:
            with self.subTest(override=key):
                self.assertIn(
                    key,
                    group_vars,
                    f"{key} must stay declared in {_GROUP_VARS} so an operator "
                    f"can discover it without reading the plugin.",
                )
                self.assertIsNone(
                    group_vars[key],
                    f"{key} must default to null. Any other value would make "
                    f"the override always win and the measurement dead code.",
                )

    def test_no_consumer_reads_the_fragile_facts(self) -> None:
        offenders = [
            f"{path.relative_to(PROJECT_ROOT)}: {fact}"
            for path in (*_CONSUMERS, _GROUP_VARS)
            for fact in _FRAGILE_FACTS
            if fact in read_text(str(path))
        ]
        self.assertEqual(
            offenders,
            [],
            f"These files dereference a fact that Ansible's hardware collector "
            f"stops producing as soon as one block device is unreadable. Read "
            f"the matching RESOURCE_* constant instead. Found {offenders}.",
        )

    def test_the_plugin_substitutes_no_value_of_its_own(self) -> None:
        source = read_text(str(_PLUGIN))
        for key in _OVERRIDE_KEYS:
            with self.subTest(override=key):
                self.assertIn(
                    key,
                    source,
                    f"{_PLUGIN} must name {key} in the failure it raises, or an "
                    f"operator is told what broke without being told how to fix "
                    f"it.",
                )
        self.assertNotIn(
            "cpu_count() or ",
            source,
            f"{_PLUGIN} must never fall back to a guessed CPU count. A guessed "
            f"figure sizes every container on the host wrong and nothing "
            f"reports it.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

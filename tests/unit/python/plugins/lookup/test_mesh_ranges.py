from __future__ import annotations

import unittest

from ansible.errors import AnsibleError

import plugins.lookup.mesh_ranges as module

POOLS = "{{ [WIREGUARD_SUBNET_POOL] }}"


class _Templar:
    def __init__(self, rendered):
        self.rendered = rendered

    def template(self, value, **_):
        return self.rendered.get(value, value) if isinstance(value, str) else value


def _run(pools, rendered=None):
    lookup = module.LookupModule()
    lookup._templar = _Templar(rendered or {})
    return lookup.run(None, variables={"WIREGUARD_SUBNET_POOLS": pools})[0]


class TestMeshRanges(unittest.TestCase):
    def test_the_declared_template_is_rendered_before_it_is_returned(self):
        self.assertEqual(
            _run(POOLS, {POOLS: ["10.100.0.0/16"]}),
            ["10.100.0.0/16"],
        )

    def test_a_pool_that_stays_a_template_fails_instead_of_leaking(self):
        with self.assertRaises(AnsibleError) as raised:
            _run(POOLS)
        self.assertIn("did not render", str(raised.exception))

    def test_a_literal_list_passes_through(self):
        self.assertEqual(_run(["10.100.0.0/16"]), ["10.100.0.0/16"])

    def test_terms_are_refused(self):
        with self.assertRaises(AnsibleError):
            module.LookupModule().run(["x"], variables={})


if __name__ == "__main__":
    unittest.main()

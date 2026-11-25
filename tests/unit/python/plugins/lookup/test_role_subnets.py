from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup import role_subnets
from plugins.lookup.role_subnets import LookupModule

SUBNETS = {
    "web-app-bigbluebutton": "10.7.7.0/24",
    "web-app-openpost": "192.88.99.0/24",
}


class _Templar:
    def __init__(self, rendered):
        self.rendered = rendered
        self.calls: list[str] = []

    def template(self, value):
        self.calls.append(str(value))
        return self.rendered


def _run(terms, templar=None):
    lookup = LookupModule()
    lookup._templar = templar
    lookup._loader = mock.MagicMock()
    config = mock.MagicMock(
        run=lambda args, **_: [SUBNETS.get(args[0])],
    )
    with mock.patch.object(role_subnets, "lookup_loader") as loader:
        loader.get.return_value = config
        return lookup.run(terms, variables={})[0]


class TestRoleSubnets(unittest.TestCase):
    def test_role_ids_and_lists_of_them_resolve_in_order(self):
        self.assertEqual(
            _run(["web-app-openpost", ["web-app-bigbluebutton"]]),
            ["192.88.99.0/24", "10.7.7.0/24"],
        )

    def test_an_unrendered_group_var_is_rendered_before_its_ids_are_read(self):
        templar = _Templar(["web-app-bigbluebutton", "web-app-openpost"])
        self.assertEqual(
            _run(["{{ lookup('role_subnet_exceptions') }}"], templar),
            ["10.7.7.0/24", "192.88.99.0/24"],
        )
        self.assertEqual(templar.calls, ["{{ lookup('role_subnet_exceptions') }}"])

    def test_a_plain_role_id_is_not_templated(self):
        templar = _Templar(["unused"])
        _run(["web-app-openpost"], templar)
        self.assertEqual(templar.calls, [])

    def test_a_role_without_a_subnet_fails(self):
        with self.assertRaises(AnsibleError):
            _run(["web-app-unknown"])

    def test_no_role_fails(self):
        with self.assertRaises(AnsibleError):
            _run([])


if __name__ == "__main__":
    unittest.main()

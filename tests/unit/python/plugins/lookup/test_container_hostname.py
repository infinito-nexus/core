import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.container_hostname import LookupModule


class TestContainerHostnameLookup(unittest.TestCase):
    def test_delegates_to_bounded_name_at_the_kernel_limit(self):
        bounded = MagicMock()
        bounded.run.return_value = ["xwiki"]
        with patch(
            "plugins.lookup.container_hostname.lookup_loader.get",
            return_value=bounded,
        ) as get:
            result = LookupModule().run(["web-app-xwiki"], variables={"k": "v"})

        self.assertEqual(result, ["xwiki"])
        self.assertEqual(get.call_args.args[0], "bounded_name")
        bounded.run.assert_called_once_with(["web-app-xwiki", 63], variables={"k": "v"})

    def test_bad_arity_raises(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([], variables={})


if __name__ == "__main__":
    unittest.main()

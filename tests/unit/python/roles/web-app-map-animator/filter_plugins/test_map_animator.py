import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

NODE_REFERENCE = (
    "scrypt:dvtV6SnAa5ewHDWVDuX3Lw:uLDiX005lE8Pc4myyQ8oQdX4DCapRbDypB3meqe1omA"
)


def _load_module():
    plugin_path = (
        PROJECT_ROOT
        / "roles"
        / "web-app-map-animator"
        / "filter_plugins"
        / "map_animator.py"
    )
    spec = importlib.util.spec_from_file_location("map_animator_filter", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestMapAnimatorPasswordHash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hash = staticmethod(_load_module().map_animator_password_hash)

    def test_matches_node_scrypt_of_the_server(self):
        self.assertEqual(self.hash("pässwörd1", "key", "alice"), NODE_REFERENCE)

    def test_salt_differs_per_user(self):
        self.assertNotEqual(
            self.hash("same", "key", "alice").split(":")[1],
            self.hash("same", "key", "bob").split(":")[1],
        )

    def test_rejects_missing_input(self):
        for args in (("", "key", "alice"), ("pw", "", "alice"), ("pw", "key", "")):
            with self.subTest(args=args), self.assertRaises(AnsibleFilterError):
                self.hash(*args)


class TestMapAnimatorUsersFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.users_file = staticmethod(_load_module().map_animator_users_file)

    def test_one_sorted_line_per_user_and_stable(self):
        directory = {
            "zed": {"username": "zed", "password": "pinned-z"},
            "alice": {"username": "alice", "password": "pinned-a"},
        }
        text = self.users_file(directory, "key")
        self.assertEqual(
            [line.split(":")[0] for line in text.splitlines()], ["alice", "zed"]
        )
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(text, self.users_file(directory, "key"))

    def test_leaves_out_bots_and_host_logins(self):
        directory = {
            "administrator": {
                "username": "administrator",
                "password": "become",
                "accounts": ["host", "mailbox", "identity"],
            },
            "newsletter": {
                "username": "newsletter",
                "password": "bot",
                "roles": ["bot"],
            },
            "biber": {
                "username": "biber",
                "password": "human",
                "accounts": ["identity"],
            },
        }
        text = self.users_file(directory, "key")
        self.assertEqual([line.split(":")[0] for line in text.splitlines()], ["biber"])

    def test_no_users_renders_an_empty_file(self):
        self.assertEqual(self.users_file({}, "key"), "")


if __name__ == "__main__":
    unittest.main()

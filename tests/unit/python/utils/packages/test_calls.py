import unittest

from utils.packages.calls import manager_args

ARGS = {"name": ["wazuh-agent"], "state": "present"}


class TestManagerArgs(unittest.TestCase):
    def test_apt_pins_with_equals_and_overrides_its_hold(self):
        self.assertEqual(
            manager_args("apt", ARGS, "4.14.6-1", None),
            {
                "name": ["wazuh-agent=4.14.6-1"],
                "state": "present",
                "install_recommends": False,
                "allow_change_held_packages": True,
            },
        )

    def test_dnf_pins_with_a_dash_and_lifts_only_the_given_repo(self):
        self.assertEqual(
            manager_args("dnf", ARGS, "4.14.6-1", "wazuh"),
            {"name": ["wazuh-agent-4.14.6-1"], "state": "present", "disable_excludes": "wazuh"},
        )

    def test_dnf5_uses_the_dnf_format(self):
        self.assertEqual(manager_args("dnf5", ARGS, "4.14.6-1", None)["name"], ["wazuh-agent-4.14.6-1"])

    def test_apt_ignores_disable_excludes(self):
        self.assertNotIn("disable_excludes", manager_args("apt", ARGS, "4.14.6-1", "wazuh"))

    def test_an_unpinned_apt_install_keeps_the_hold_and_skips_recommends(self):
        self.assertEqual(manager_args("apt", ARGS, None, None), {**ARGS, "install_recommends": False})

    def test_an_unpinned_dnf_install_is_unchanged(self):
        self.assertEqual(manager_args("dnf", ARGS, None, None), ARGS)

    def test_a_manager_without_a_pin_format_raises(self):
        with self.assertRaises(ValueError):
            manager_args("pacman", ARGS, "4.14.6-1", None)

    def test_the_input_arguments_are_not_changed(self):
        args = dict(ARGS)
        manager_args("apt", args, "4.14.6-1", None)
        self.assertEqual(args, ARGS)


if __name__ == "__main__":
    unittest.main()

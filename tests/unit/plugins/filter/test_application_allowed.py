import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.application_allowed import application_allowed


class TestApplicationAllowed(unittest.TestCase):
    def test_application_not_in_group(self):
        # application not in group_names should always return False
        self.assertFalse(application_allowed("app1", ["other_group"], None))
        self.assertFalse(application_allowed("app1", ["other_group"], []))
        self.assertFalse(application_allowed("app1", ["other_group"], ["app1"]))

    def test_no_allowed_applications_allows_group_items(self):
        # allowed_applications is None or empty -> allow if in group
        self.assertTrue(application_allowed("app1", ["app1", "app2"], None))
        # empty list treated as no filter -> allow all in group
        self.assertTrue(application_allowed("app2", ["app1", "app2"], []))

    def test_allowed_applications_list(self):
        group = ["app1", "app2", "app3"]
        allowed = ["app2", "app3"]
        self.assertFalse(application_allowed("app1", group, allowed))
        self.assertTrue(application_allowed("app2", group, allowed))
        self.assertTrue(application_allowed("app3", group, allowed))

    def test_allowed_applications_wrong_type(self):
        # invalid allowed_applications type
        with self.assertRaises(AnsibleFilterError):
            application_allowed("app1", ["app1"], allowed_applications=123)

    def test_group_names_wrong_type(self):
        # invalid group_names type
        with self.assertRaises(AnsibleFilterError):
            application_allowed(1232312, "not_a_list", None)

    def test_allowed_applications_edge_cases(self):
        # whitespace-only entries do not affect result
        group = ["app1"]
        allowed = ["app1", "  ", ""]
        self.assertTrue(application_allowed("app1", group, allowed))
        # application in group but not listed -> false
        self.assertFalse(application_allowed("app2", ["app2"], allowed))


if __name__ == "__main__":
    unittest.main()

import unittest

from utils.packages.facts import distribution_and_family, read_fact


class TestReadFact(unittest.TestCase):
    def test_bare_key_from_task_vars(self):
        self.assertEqual(read_fact({"pkg_mgr": "apt"}, "pkg_mgr"), "apt")

    def test_prefixed_key_from_the_setup_module(self):
        self.assertEqual(read_fact({"ansible_pkg_mgr": " dnf "}, "pkg_mgr"), "dnf")

    def test_an_absent_fact_reads_empty(self):
        self.assertEqual(read_fact({}, "pkg_mgr"), "")


class TestDistributionAndFamily(unittest.TestCase):
    def test_bare_keys_from_task_vars(self):
        self.assertEqual(
            distribution_and_family({"distribution": "Fedora", "os_family": "RedHat"}),
            ("fedora", "RedHat"),
        )

    def test_prefixed_keys_from_the_setup_module(self):
        self.assertEqual(
            distribution_and_family(
                {"ansible_distribution": "Ubuntu", "ansible_os_family": "Debian"}
            ),
            ("ubuntu", "Debian"),
        )

    def test_missing_facts_read_empty(self):
        self.assertEqual(distribution_and_family({}), ("", ""))

    def test_a_half_answer_is_no_answer(self):
        self.assertEqual(distribution_and_family({"distribution": "Fedora"}), ("", ""))


if __name__ == "__main__":
    unittest.main()

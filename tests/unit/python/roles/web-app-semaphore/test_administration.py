import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ADMINISTRATION = PROJECT_ROOT / "roles" / "web-app-semaphore" / "Administration.md"


def missing_failure_facts(text):
    """
    Args:
        text: the Administration page.

    Returns:
        The single-point-of-failure facts the page does not name.
    """
    wanted = (
        "## Single point of failure",
        "single point of failure for every workspace",
        "`access_key_encryption`",
        "`workspace apply`",
        "restore time",
        "workspace drill: restore took",
    )
    return [token for token in wanted if token not in text]


class TestAdministration(unittest.TestCase):
    def test_administration_names_the_single_point_of_failure(self):  # nocheck: test.text-presence -- requirement 112 names this docs check as its proof  # fmt: skip
        text = read_text(str(ADMINISTRATION))
        self.assertEqual(missing_failure_facts(text), [])

    def test_negative_control_a_page_without_the_failure_section_fails(self):
        missing = missing_failure_facts("# Administration\n")
        self.assertIn("## Single point of failure", missing)


if __name__ == "__main__":
    unittest.main()

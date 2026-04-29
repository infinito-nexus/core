import re
import unittest

from plugins.filter.get_all_application_ids import get_all_application_ids
from utils.cache.files import iter_project_files_with_content


class TestGetDomainApplicationIds(unittest.TestCase):
    """
    Integration test to verify that all string literals passed to get_domain()
    correspond to valid application_id values defined in roles/*/vars/main.yml.
    """

    GET_DOMAIN_PATTERN = re.compile(r"get_domain\(\s*['\"]([^'\"]+)['\"]\s*\)")

    def test_get_domain_literals_are_valid_ids(self):
        # Collect all application IDs from roles
        valid_ids = set(get_all_application_ids())

        # Walk project .py files (skip tests/, served from cache)
        invalid_usages = []
        for path, content in iter_project_files_with_content(
            extensions=(".py",), exclude_tests=True
        ):
            for match in self.GET_DOMAIN_PATTERN.finditer(content):
                literal = match.group(1)
                if literal not in valid_ids:
                    invalid_usages.append((path, literal))

        if invalid_usages:
            msgs = [
                f"{path}: '{lit}' is not a valid application_id"
                for path, lit in invalid_usages
            ]
            self.fail("Found invalid get_domain() usages:\n" + "\n".join(msgs))


if __name__ == "__main__":
    unittest.main()

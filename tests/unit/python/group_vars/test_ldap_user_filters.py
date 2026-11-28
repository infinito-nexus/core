import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

GROUP_VARS = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/12_ldap.yml"))
COMPOSITE_OPERATORS = ("&", "|")
USER_OBJECT_CLASS_FILTER = "(objectclass=inetOrgPerson)"


def composite_operands(ldap_filter: str) -> list[tuple[str, int]]:
    """Count the operands of every AND and OR composite of an RFC 4515 filter.

    Args:
        ldap_filter: the filter string.

    Returns:
        One (operator, operand count) pair per composite, in closing order.
    """
    operators: list[str] = []
    counts: list[int] = []
    composites: list[tuple[str, int]] = []
    for index, char in enumerate(ldap_filter):
        if char == "(":
            if operators and operators[-1] in COMPOSITE_OPERATORS:
                counts[-1] += 1
            operators.append(ldap_filter[index + 1 : index + 2])
            counts.append(0)
        elif char == ")":
            operator, operands = operators.pop(), counts.pop()
            if operator in COMPOSITE_OPERATORS:
                composites.append((operator, operands))
    if operators:
        raise ValueError(f"unbalanced LDAP filter: {ldap_filter}")
    return composites


def rendered_user_filters() -> dict[str, str]:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    helpers = {key: value for key, value in GROUP_VARS.items() if key.startswith("_")}
    return {
        name: env.from_string(template).render(**helpers)
        for name, template in GROUP_VARS["LDAP"]["FILTERS"]["USERS"].items()
    }


class TestLdapUserFilters(unittest.TestCase):
    """ejabberd's eldap_filter parser rejects an AND or OR with one operand,
    which RFC 4515 allows, and ejabberd then refuses to start. Every shared
    user filter must stay inside what that strictest consumer parses.
    """

    def test_the_counter_flags_a_single_operand_composite(self):
        self.assertEqual(
            composite_operands("(|(objectclass=inetOrgPerson))"), [("|", 1)]
        )
        self.assertEqual(
            composite_operands("(&(objectclass=inetOrgPerson)(uid=%uid))"),
            [("&", 2)],
        )

    def test_every_composite_of_a_shared_user_filter_has_two_operands(self):
        filters = rendered_user_filters()
        self.assertLessEqual({"ALL", "LOGIN"}, set(filters))
        for name, ldap_filter in filters.items():
            with self.subTest(filter=name, value=ldap_filter):
                single = [
                    composite
                    for composite in composite_operands(ldap_filter)
                    if composite[1] < 2
                ]
                self.assertEqual(single, [])

    def test_every_shared_user_filter_still_selects_the_user_object_class(self):
        for name, ldap_filter in rendered_user_filters().items():
            with self.subTest(filter=name):
                self.assertIn(USER_OBJECT_CLASS_FILTER, ldap_filter)


if __name__ == "__main__":
    unittest.main()

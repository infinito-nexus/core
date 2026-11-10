from __future__ import annotations

import importlib.util
import sys
import unicodedata
import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.platform_admin import platform_admin_plan

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-joomla/filter_plugins/joomla_users.py", "joomla_users"
)

HEADER = ["ID", "Username", "Name", "Email", "Blocked", "Groups"]
LEGACY = [
    "42",
    "administrator",
    "Administrator Example",
    "administrator@example.org",
    "0",
    "Registered, Super Users",
]
READER = ["43", "biber", "Biber  Test", "biber@example.org", "0", "Registered"]


def display_width(text: str) -> int:
    """Count the terminal columns Symfony's Helper::width() gives ``text``.

    Args:
        text: one table cell.

    Returns:
        2 per East Asian wide or fullwidth character, 0 per combining mark or
        format character, 1 per other character.
    """
    width = 0
    for char in text:
        if unicodedata.combining(char) or unicodedata.category(char) in {
            "Mn",
            "Me",
            "Cf",
        }:
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def table(border: str, lines: list[str]) -> str:
    """Wrap rendered rows in the title and borders of user:list.

    Args:
        border: the dash line above, between and below the rows.
        lines: the header row followed by every account row.

    Returns:
        The stdout of ``user:list``.
    """
    body = [border, lines[0], border, *lines[1:], border]
    return "\nList Users\n==========\n\n" + "\n".join(body) + "\n\n"


def user_list(rows: list[list[str]]) -> str:
    """Render ``rows`` the way SymfonyStyle::table() does for user:list.

    Args:
        rows: the cells of every account, in the order of ``HEADER``.

    Returns:
        The stdout of ``user:list``, every cell padded to its column's
        display width as Symfony's Table::renderCell() pads it.
    """
    widths = [
        max(display_width(row[column]) for row in [HEADER, *rows]) + 2
        for column in range(len(HEADER))
    ]
    border = " " + " ".join("-" * width for width in widths) + " "

    def line(row: list[str]) -> str:
        cells = (
            f" {cell}" + " " * (width - 1 - display_width(cell))
            for cell, width in zip(row, widths, strict=True)
        )
        return " " + " ".join(cells) + " "

    return table(border, [line(row) for row in [HEADER, *rows]])


def padded(*cells: tuple[str, int]) -> str:
    """Render one row from hand-counted trailing pads.

    Args:
        cells: ``(text, pad)`` per column, ``pad`` being the spaces after it.

    Returns:
        The row as Symfony prints it.
    """
    return " " + " ".join(f" {text}{' ' * pad}" for text, pad in cells) + " "


class TestJoomlaUserAccounts(unittest.TestCase):
    def test_every_row_becomes_an_account_with_its_super_user_membership(self) -> None:
        self.assertEqual(
            MODULE.joomla_user_accounts(user_list([LEGACY, READER])),
            [
                {
                    "login": "administrator",
                    "email": "administrator@example.org",
                    "admin": True,
                },
                {"login": "biber", "email": "biber@example.org", "admin": False},
            ],
        )

    def test_cjk_and_decomposed_names_keep_the_following_columns_aligned(
        self,
    ) -> None:
        output = table(
            " ---- ---------- ---------- -------------------- --------- ------------- ",
            [
                padded(
                    ("ID", 1),
                    ("Username", 1),
                    ("Name", 5),
                    ("Email", 14),
                    ("Blocked", 1),
                    ("Groups", 6),
                ),
                padded(
                    ("48", 1),
                    ("yamada", 3),
                    ("山田太郎", 1),
                    ("yamada@example.org", 1),
                    ("0", 7),
                    ("Super Users", 1),
                ),
                padded(
                    ("49", 1),
                    ("renee", 4),
                    ("Renée", 4),
                    ("renee@example.org", 2),
                    ("0", 7),
                    ("Registered", 2),
                ),
            ],
        )

        self.assertEqual(
            MODULE.joomla_user_accounts(output),
            [
                {"login": "yamada", "email": "yamada@example.org", "admin": True},
                {"login": "renee", "email": "renee@example.org", "admin": False},
            ],
        )

    def test_a_wide_username_is_read_whole(self) -> None:
        row = ["50", "山田", "Yamada", "y@example.org", "0", "Super Users"]
        self.assertEqual(
            MODULE.joomla_user_accounts(user_list([row])),
            [{"login": "山田", "email": "y@example.org", "admin": True}],
        )

    def test_a_group_title_merely_containing_super_users_is_no_membership(self) -> None:
        row = ["44", "editor", "Editor", "editor@example.org", "0", "Super Users Lite"]
        self.assertEqual(
            MODULE.joomla_user_accounts(user_list([row]))[0]["admin"], False
        )

    def test_output_without_a_table_is_refused(self) -> None:
        with self.assertRaisesRegex(AnsibleFilterError, "no account table"):
            MODULE.joomla_user_accounts("Error: could not connect to the database\n")

    def test_a_table_with_other_columns_is_refused(self) -> None:
        output = user_list([LEGACY]).replace("Blocked", "Locked ")
        with self.assertRaisesRegex(AnsibleFilterError, "expected"):
            MODULE.joomla_user_accounts(output)


class TestJoomlaPlatformAdminPlan(unittest.TestCase):
    def plan(self, rows: list[list[str]]) -> str:
        return platform_admin_plan(
            MODULE.joomla_user_accounts(user_list(rows)),
            "platformadmin",
            "platformadmin@example.org",
            "Joomla",
            False,
        )

    def test_absent_platform_administrator_is_created_next_to_a_super_user(
        self,
    ) -> None:
        self.assertEqual(self.plan([LEGACY, READER]), "create")

    def test_present_super_user_is_realigned(self) -> None:
        row = [
            "45",
            "platformadmin",
            "Platformadmin",
            "platformadmin@example.org",
            "0",
            "Super Users",
        ]
        self.assertEqual(self.plan([LEGACY, row]), "realign")

    def test_site_without_a_super_user_fails(self) -> None:
        with self.assertRaisesRegex(AnsibleFilterError, "Joomla has no administrator"):
            self.plan([READER])

    def test_email_held_by_another_account_fails_naming_it(self) -> None:
        row = [
            "46",
            "someone",
            "Someone",
            "PlatformAdmin@example.org",
            "0",
            "Registered",
        ]
        with self.assertRaisesRegex(
            AnsibleFilterError, "held by the Joomla account someone"
        ):
            self.plan([LEGACY, row])

    def test_registered_holder_of_the_username_in_another_case_is_not_promoted(
        self,
    ) -> None:
        row = ["47", "PlatformAdmin", "PA", "pa@example.org", "0", "Registered"]
        with self.assertRaisesRegex(AnsibleFilterError, "not promoted"):
            self.plan([LEGACY, row])


ADD_FAILED = "\nAdd User\n========\n\n [ERROR] {}\n\n"


class TestJoomlaUserAddConflict(unittest.TestCase):
    def conflict(self, output: str) -> str:
        return MODULE.joomla_user_add_conflict(
            output, "platformadmin", "platformadmin@example.org"
        )

    def test_a_taken_username_names_the_group_less_account(self) -> None:
        message = self.conflict(ADD_FAILED.format("The username already exists!"))

        self.assertIn("'platformadmin'", message)
        self.assertIn("belongs to no user group", message)
        self.assertIn("add it to Super Users", message)

    def test_a_taken_email_names_the_address_of_the_group_less_account(self) -> None:
        message = self.conflict(ADD_FAILED.format("The email address already exists!"))

        self.assertIn("'platformadmin@example.org'", message)
        self.assertIn("without any user group", message)

    def test_any_other_refusal_is_left_to_the_task_itself(self) -> None:
        self.assertEqual(
            self.conflict(ADD_FAILED.format("The email address is invalid!")), ""
        )

    def test_output_that_is_no_string_is_no_conflict(self) -> None:
        self.assertEqual(self.conflict(None), "")


if __name__ == "__main__":
    unittest.main()

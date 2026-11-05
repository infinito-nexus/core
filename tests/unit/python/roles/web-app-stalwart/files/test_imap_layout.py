import importlib.util
import sys
import unittest

from . import PROJECT_ROOT

SCRIPTS = PROJECT_ROOT / "roles/web-app-stalwart/files/python"
LIST_LINES = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
    b'(\\HasNoChildren \\Junk) "/" "Junk Mail"',
    b'(\\HasNoChildren) "/" Archive',
]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, str(SCRIPTS / f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_module():
    _load("mailu_maildir")
    return _load("imap_layout")


class _FakeImap:
    def __init__(self, existing_headers: list[bytes] | None = None, list_lines=None):
        self._existing_headers = existing_headers or []
        self._list_lines = LIST_LINES if list_lines is None else list_lines

    def list(self):
        return "OK", list(self._list_lines)

    def search(self, charset, *criteria):
        nums = b" ".join(
            str(i + 1).encode() for i in range(len(self._existing_headers))
        )
        return "OK", [nums]

    def fetch(self, message_set, message_parts):
        data = [
            ((f"{i + 1} ()").encode(), header)
            for i, header in enumerate(self._existing_headers)
        ]
        return "OK", data


class TestServerLayout(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()
        self.layout = self.m.server_layout(_FakeImap())

    def test_reads_separator_and_special_use(self):
        self.assertEqual(self.layout.separator, "/")
        self.assertEqual(
            self.layout.special_use, {"\\Sent": "Sent Items", "\\Junk": "Junk Mail"}
        )

    def test_nested_folder_uses_the_server_separator(self):
        self.assertEqual(
            self.m.destination_mailbox(".Archive.2024", self.layout), "Archive/2024"
        )

    def test_special_folder_lands_in_the_special_use_folder(self):
        self.assertEqual(self.m.destination_mailbox(".Sent", self.layout), "Sent Items")
        self.assertEqual(self.m.destination_mailbox(".Spam", self.layout), "Junk Mail")

    def test_special_name_without_server_counterpart_keeps_its_name(self):
        self.assertEqual(self.m.destination_mailbox(".Drafts", self.layout), "Drafts")

    def test_ambiguous_separator_fails(self):
        imap = _FakeImap(list_lines=[b'(\\X) "/" A', b'(\\X) "." B'])
        with self.assertRaises(self.m.MigrationError):
            self.m.server_layout(imap)

    def test_imap_quote_escapes(self):
        self.assertEqual(self.m.imap_quote('My "x"\\y'), '"My \\"x\\"\\\\y"')


class TestExistingKeys(unittest.TestCase):
    def test_collects_the_server_side_keys(self):
        m = _load_module()
        imap = _FakeImap(
            existing_headers=[b"Message-ID: <a@x>\r\n\r\n", b"X: 1\r\n\r\n"]
        )
        self.assertEqual(m.existing_keys(imap), {"<a@x>"})


if __name__ == "__main__":
    unittest.main()

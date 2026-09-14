"""Unit tests for ``cli.administration.inventory.credentials.vault``."""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from ansible.errors import AnsibleError

from cli.administration.inventory.credentials.vault import (
    _make_vault_scalar_from_text,
    _vault_body,
    is_ruamel_vault,
    is_vault_encrypted,
    to_vault_block,
)
from utils.handler.vault import VaultHandler, VaultScalar


class TestIsVaultEncrypted(unittest.TestCase):
    def test_vault_scalar_is_detected(self):
        self.assertTrue(is_vault_encrypted(VaultScalar("body")))

    def test_ansible_vault_string_is_detected(self):
        self.assertTrue(is_vault_encrypted("$ANSIBLE_VAULT;1.1;AES256\nXX"))

    def test_inline_vault_header_is_detected(self):
        self.assertTrue(is_vault_encrypted("!vault | $ANSIBLE_VAULT;..."))

    def test_plain_string_is_not_detected(self):
        self.assertFalse(is_vault_encrypted("plain"))

    def test_dict_is_not_detected(self):
        self.assertFalse(is_vault_encrypted({"key": "value"}))

    def test_none_is_not_detected(self):
        self.assertFalse(is_vault_encrypted(None))


class TestIsRuamelVault(unittest.TestCase):
    def test_ruamel_scalar_with_vault_tag(self):
        scalar = _make_vault_scalar_from_text("$ANSIBLE_VAULT;1.1;AES256\nBODY")
        self.assertTrue(is_ruamel_vault(scalar))

    def test_plain_string_returns_false(self):
        self.assertFalse(is_ruamel_vault("plain"))

    def test_arbitrary_object_returns_false(self):
        self.assertFalse(is_ruamel_vault(object()))


class TestVaultBody(unittest.TestCase):
    def test_strips_leading_header(self):
        text = "!vault |\n  $ANSIBLE_VAULT;1.1;AES256\n  BODY"
        body = _vault_body(text)
        self.assertTrue(body.lstrip().startswith("$ANSIBLE_VAULT"))

    def test_no_header_returns_text_unchanged(self):
        text = "no ansible_vault here"
        self.assertEqual(_vault_body(text), text)


class TestMakeVaultScalarFromText(unittest.TestCase):
    def test_returns_ruamel_vault_scalar(self):
        scalar = _make_vault_scalar_from_text("$ANSIBLE_VAULT;1.1;AES256\nXX")
        self.assertTrue(is_ruamel_vault(scalar))


class TestToVaultBlock(unittest.TestCase):
    def setUp(self):
        self.handler = VaultHandler("dummy_pw_file")

    def test_empty_string_stays_plain(self):
        self.assertEqual(to_vault_block(self.handler, "", "k"), "")

    def test_ruamel_vault_scalar_passes_through(self):
        scalar = _make_vault_scalar_from_text("$ANSIBLE_VAULT;1.1;AES256\nXX")
        self.assertIs(to_vault_block(self.handler, scalar, "k"), scalar)

    def test_vault_scalar_is_rewrapped(self):
        out = to_vault_block(self.handler, VaultScalar("$ANSIBLE_VAULT;...\nXX"), "k")
        self.assertTrue(is_ruamel_vault(out))

    def test_ansible_vault_string_is_rewrapped(self):
        out = to_vault_block(self.handler, "$ANSIBLE_VAULT;1.1;AES256\nXX", "k")
        self.assertTrue(is_ruamel_vault(out))

    def test_plaintext_is_encrypted_via_handler(self):
        fake = "!vault |\n  $ANSIBLE_VAULT;1.1;AES256\n    ENCRYPTED"
        with unittest.mock.patch.object(
            self.handler, "encrypt_string", return_value=fake
        ) as encrypt:
            out = to_vault_block(self.handler, "secret", "label")
        encrypt.assert_called_once_with("secret", "label")
        self.assertTrue(is_ruamel_vault(out))


class TestVaultHandlerIntegration(unittest.TestCase):
    """Black-box coverage of the VaultHandler that ``to_vault_block``
    delegates to for plaintext encryption."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.password_file = Path(self._tmp.name) / "vault.pw"
        self.password_file.write_text("unit-test-vault-password\n", encoding="utf-8")
        self.handler = VaultHandler(str(self.password_file))

    def test_encrypt_string_round_trips_through_the_vault(self):
        snippet = self.handler.encrypt_string("plain_val", "name")
        body = "\n".join(line.strip() for line in snippet.splitlines()[1:])
        self.assertEqual(self.handler._vault.decrypt(body).decode(), "plain_val")

    def test_encrypt_string_keeps_the_layout_encrypt_leaves_unindents(self):
        lines = self.handler.encrypt_string("plain_val", "name").splitlines()
        self.assertEqual(
            lines[0], "name: !vault |", "first line must stay the YAML key and tag"
        )
        indents = {len(line) - len(line.lstrip()) for line in lines[1:]}
        self.assertEqual(
            indents, {10}, "encrypt_leaves strips a uniform body indent of 10"
        )
        self.assertEqual(lines[1].strip(), "$ANSIBLE_VAULT;1.1;AES256")

    def test_values_that_look_like_flags_still_encrypt(self):
        for value in ("-leading-dash", "--stdin-name"):
            with self.subTest(value=value):
                snippet = self.handler.encrypt_string(value, "k")
                body = "\n".join(line.strip() for line in snippet.splitlines()[1:])
                self.assertEqual(self.handler._vault.decrypt(body).decode(), value)

    def test_missing_password_file_raises(self):
        with self.assertRaises(AnsibleError):
            VaultHandler("dummy_pw_file").encrypt_string("plain_val", "name")

    def test_password_file_whitespace_is_stripped_like_ansible_does(self):
        padded = Path(self._tmp.name) / "padded.pw"
        padded.write_text("  unit-test-vault-password  \n", encoding="utf-8")
        snippet = VaultHandler(str(padded)).encrypt_string("plain_val", "name")
        body = "\n".join(line.strip() for line in snippet.splitlines()[1:])
        self.assertEqual(self.handler._vault.decrypt(body).decode(), "plain_val")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

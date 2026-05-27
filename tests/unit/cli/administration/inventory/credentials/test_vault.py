"""Unit tests for ``cli.administration.inventory.credentials.vault``."""

from __future__ import annotations

import subprocess
import unittest
import unittest.mock

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

    def test_encrypt_string_success(self):
        handler = VaultHandler("dummy_pw_file")
        fake_output = "Encrypted data"
        completed = subprocess.CompletedProcess(
            args=["ansible-vault"], returncode=0, stdout=fake_output, stderr=""
        )
        with unittest.mock.patch("subprocess.run", return_value=completed) as proc_run:
            result = handler.encrypt_string("plain_val", "name")
            proc_run.assert_called_once()
            self.assertEqual(result, fake_output)

    def test_encrypt_string_failure_raises(self):
        handler = VaultHandler("dummy_pw_file")
        completed = subprocess.CompletedProcess(
            args=["ansible-vault"], returncode=1, stdout="", stderr="error"
        )
        with (
            unittest.mock.patch("subprocess.run", return_value=completed),
            self.assertRaises(RuntimeError),
        ):
            handler.encrypt_string("plain_val", "name")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

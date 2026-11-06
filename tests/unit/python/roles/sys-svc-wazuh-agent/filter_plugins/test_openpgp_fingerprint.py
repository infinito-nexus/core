import base64
import hashlib
import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "sys-svc-wazuh-agent"
_spec = importlib.util.spec_from_file_location(
    "openpgp_fingerprint", ROLE / "filter_plugins" / "openpgp_fingerprint.py"
)
openpgp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(openpgp)

BODY = bytes([4]) + bytes(range(1, 200))


def expected(body):
    prefix = b"\x99" + len(body).to_bytes(2, "big")
    digest = hashlib.sha1(prefix + body)  # noqa: S324 - RFC 4880 defines OpenPGP v4 fingerprints as SHA-1
    return digest.hexdigest().upper()


def armor(packet, header=True):
    lines = ["-----BEGIN PGP PUBLIC KEY BLOCK-----"]
    if header:
        lines += ["Version: test", ""]
    encoded = base64.b64encode(packet).decode()
    lines += [encoded[i : i + 64] for i in range(0, len(encoded), 64)]
    lines += ["=abcd", "-----END PGP PUBLIC KEY BLOCK-----"]
    return "\n".join(lines) + "\n"


class TestOpenpgpFingerprint(unittest.TestCase):
    def test_old_format_packet_with_armor_header(self):
        packet = bytes([0x98, len(BODY)]) + BODY
        self.assertEqual(openpgp.openpgp_fingerprint(armor(packet)), expected(BODY))

    def test_old_format_two_byte_length_without_header(self):
        body = bytes([4]) + bytes(300)
        packet = bytes([0x99]) + len(body).to_bytes(2, "big") + body
        self.assertEqual(
            openpgp.openpgp_fingerprint(armor(packet, header=False)), expected(body)
        )

    def test_new_format_packet(self):
        body = BODY[:150]
        packet = bytes([0xC6, len(body)]) + body
        self.assertEqual(openpgp.openpgp_fingerprint(armor(packet)), expected(body))

    def test_new_format_two_octet_length(self):
        body = bytes([4]) + bytes(400)
        first, second = divmod(len(body) - 192, 256)
        packet = bytes([0xC6, first + 192, second]) + body
        self.assertEqual(openpgp.openpgp_fingerprint(armor(packet)), expected(body))

    def test_only_the_primary_key_counts(self):
        subkey = bytes([0xB8, 3, 4, 9, 9])
        packet = bytes([0x98, len(BODY)]) + BODY + subkey
        self.assertEqual(openpgp.openpgp_fingerprint(armor(packet)), expected(BODY))

    def test_rejects_other_versions_and_packets(self):
        for packet in (bytes([0x98, 3, 5, 1, 2]), bytes([0xB4, 3, 4, 1, 2])):
            with self.assertRaises(AnsibleFilterError):
                openpgp.openpgp_fingerprint(armor(packet))
        with self.assertRaises(AnsibleFilterError):
            openpgp.openpgp_fingerprint("not a key")

    def test_pinned_fingerprint_has_the_form_the_filter_returns(self):
        pinned = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))[
            "WAZUH_AGENT_GPG_KEY_FINGERPRINT"
        ]
        self.assertRegex(pinned, r"^[0-9A-F]{40}$")


if __name__ == "__main__":
    unittest.main()

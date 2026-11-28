import base64
import importlib.util
import json
import unittest

from ansible.errors import AnsibleFilterError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from utils.manager.value_generator import ValueGenerator

from . import PROJECT_ROOT

PLUGIN = PROJECT_ROOT / "roles" / "web-app-atmo" / "filter_plugins" / "atmo_jwk.py"
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _filter():
    spec = importlib.util.spec_from_file_location("atmo_jwk_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()["atmo_client_assertion_jwk"]


def _int(value):
    return int.from_bytes(
        base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big"
    )


class TestClientAssertionJwk(unittest.TestCase):
    def setUp(self):
        self.jwk_filter = _filter()

    def test_vapid_private_scalar_becomes_a_consistent_es256_jwk(self):
        scalar, public = ValueGenerator().generate_vapid_keypair()
        jwk = json.loads(self.jwk_filter(scalar, "main-key"))
        self.assertEqual(set(jwk), {"alg", "crv", "d", "kid", "kty", "x", "y"})
        self.assertEqual(
            (jwk["alg"], jwk["crv"], jwk["kty"], jwk["kid"]),
            ("ES256", "P-256", "EC", "main-key"),
        )
        self.assertEqual(jwk["d"], scalar)
        point = base64.urlsafe_b64decode(public + "=" * (-len(public) % 4))
        self.assertEqual(base64.urlsafe_b64decode(jwk["x"] + "=="), point[1:33])
        self.assertEqual(base64.urlsafe_b64decode(jwk["y"] + "=="), point[33:65])

    def test_derived_key_signs_what_its_public_half_verifies(self):
        scalar, _public = ValueGenerator().generate_vapid_keypair()
        jwk = json.loads(self.jwk_filter(scalar, "main-key"))
        private = ec.derive_private_key(_int(jwk["d"]), ec.SECP256R1())
        public = ec.EllipticCurvePublicNumbers(
            _int(jwk["x"]), _int(jwk["y"]), ec.SECP256R1()
        ).public_key()
        signature = private.sign(b"client-assertion", ec.ECDSA(hashes.SHA256()))
        public.verify(signature, b"client-assertion", ec.ECDSA(hashes.SHA256()))

    def test_output_is_stable_for_the_same_scalar(self):
        scalar, _public = ValueGenerator().generate_vapid_keypair()
        self.assertEqual(
            self.jwk_filter(scalar, "main-key"), self.jwk_filter(scalar, "main-key")
        )

    def test_invalid_inputs_fail_loudly(self):
        order = (
            base64.urlsafe_b64encode(P256_ORDER.to_bytes(32, "big"))
            .rstrip(b"=")
            .decode()
        )
        cases = {
            "empty": ("", "main-key"),
            "none": (None, "main-key"),
            "short": ("AAAA", "main-key"),
            "not base64": ("!!!!", "main-key"),
            "zero": ("A" * 43, "main-key"),
            "group order": (order, "main-key"),
            "empty kid": (ValueGenerator().generate_vapid_keypair()[0], " "),
        }
        for label, (scalar, kid) in cases.items():
            with self.subTest(label), self.assertRaises(AnsibleFilterError):
                self.jwk_filter(scalar, kid)


if __name__ == "__main__":
    unittest.main()

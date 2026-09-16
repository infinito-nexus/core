import importlib.util
import unittest

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "sys-ctl-hlth-csp" / "files" / "python" / "script.py"
ONION = "mirror.b5abfs7uwr23x6vbjxqjatyscpmkm6qkmkla7eyapdi4zpwtrz6o4nqd.onion"
DOMAINS = ["mirror.infinito.test", ONION, "html.infinito.test"]


def _expand(accept_status, domains=None):
    spec = importlib.util.spec_from_file_location("csp_wrapper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.expand_accept_status(
        accept_status, DOMAINS if domains is None else domains
    )


class TestAcceptStatusReachesOnions(unittest.TestCase):
    def test_the_onion_sibling_inherits_the_declaration(self):
        expanded = _expand(["mirror.infinito.test=404"])

        self.assertIn(
            f"{ONION}=404",
            expanded,
            "the checker matches accepted codes by hostname, so a code declared "
            "for the clearnet vhost never reaches its onion twin on its own",
        )

    def test_a_vhost_without_an_onion_twin_gains_nothing(self):
        self.assertEqual(
            _expand(["html.infinito.test=403"]), ["html.infinito.test=403"]
        )

    def test_several_codes_carry_over_unchanged(self):
        expanded = _expand(["mirror.infinito.test=301,302,404"])

        self.assertIn(f"{ONION}=301,302,404", expanded)

    def test_an_onion_entry_is_not_expanded_again(self):
        self.assertEqual(_expand([f"{ONION}=404"]), [f"{ONION}=404"])

    def test_an_entry_without_codes_is_left_alone(self):
        self.assertEqual(_expand(["mirror.infinito.test"]), ["mirror.infinito.test"])

    def test_only_the_matching_label_is_extended(self):
        expanded = _expand(["html.infinito.test=403", "mirror.infinito.test=404"])

        self.assertEqual(
            [e for e in expanded if e.endswith(".onion=404")], [f"{ONION}=404"]
        )
        self.assertEqual([e for e in expanded if e.endswith(".onion=403")], [])


if __name__ == "__main__":
    unittest.main()

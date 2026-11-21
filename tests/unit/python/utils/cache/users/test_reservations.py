import unittest

from utils.cache.users.reservations import materialize_domain_label_reservations


class TestDomainLabelReservations(unittest.TestCase):
    def test_every_label_of_the_primary_domain_is_reserved(self):
        out = materialize_domain_label_reservations(
            {}, {"DOMAIN_PRIMARY": "https://infinito.nexus/path"}
        )
        self.assertEqual(
            [entry["username"] for entry in out.values()], ["infinito", "nexus"]
        )
        self.assertTrue(all(entry["accounts"] == [] for entry in out.values()))

    def test_the_mail_domain_stands_in_for_a_missing_primary_domain(self):
        out = materialize_domain_label_reservations(
            {"alice": {"username": "alice"}}, {"SYSTEM_EMAIL_DOMAIN": "mail.example"}
        )
        self.assertEqual(out["alice"], {"username": "alice"})
        self.assertEqual(out["domain_label_0"]["username"], "mail")
        self.assertEqual(out["domain_label_1"]["username"], "example")


if __name__ == "__main__":
    unittest.main()

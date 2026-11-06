from __future__ import annotations

import unittest

from utils.licensing.rights import FIELDS, context_of, resolve, table

EXPECTED_CONTEXT = {
    "MIT": "permissive",
    "Apache-2.0": "permissive",
    "BSD-3-Clause": "permissive",
    "CC0-1.0": "permissive",
    "PostgreSQL": "permissive",
    "GPL-2.0-only": "copyleft",
    "GPL-3.0-only": "copyleft",
    "LGPL-3.0-or-later": "copyleft",
    "MPL-2.0": "copyleft",
    "EPL-1.0": "copyleft",
    "AGPL-3.0-only": "copyleft-network",
    "AGPL-3.0-or-later": "copyleft-network",
    "EUPL-1.2": "copyleft-network",
    "OSL-3.0": "copyleft-network",
    "Elastic-2.0": "source-available",
    "BUSL-1.1": "source-available",
    "SSPL-1.0": "source-available",
    "CC-BY-NC-4.0": "non-commercial",
    "LicenseRef-Infinito-Nexus-Community": "non-commercial",
    "LicenseRef-Baserow-Premium": "proprietary",
}

EXPECTED_EXPRESSION = {
    "MIT AND BSD-3-Clause": "permissive",
    "MPL-2.0 AND LGPL-3.0-or-later": "copyleft",
    "EUPL-1.2 AND CC-BY-NC-ND-4.0": "non-commercial",
    "MIT AND LicenseRef-Baserow-Premium": "proprietary",
    "MIT OR Apache-2.0": "permissive",
    "GPL-2.0-only OR GPL-3.0-only": "copyleft",
    "AGPL-3.0-only OR LicenseRef-RSALv2 OR SSPL-1.0": "copyleft-network",
    "Elastic-2.0 OR SSPL-1.0 OR AGPL-3.0-only": "copyleft-network",
}


class TestLicenceTable(unittest.TestCase):
    def test_every_entry_declares_every_field(self):
        incomplete = {
            name: sorted({*FIELDS, "open_source"} - set(row))
            for name, row in table().items()
            if {*FIELDS, "open_source"} - set(row)
        }
        self.assertEqual({}, incomplete)

    def test_every_value_is_a_bool(self):
        wrong = [
            f"{name}.{field}"
            for name, row in table().items()
            for field in (*FIELDS, "open_source")
            if not isinstance(row.get(field), bool)
        ]
        self.assertEqual([], wrong)


class TestContextDerivation(unittest.TestCase):
    def test_each_licence_derives_its_expected_context(self):
        for spdx, expected in EXPECTED_CONTEXT.items():
            with self.subTest(spdx=spdx):
                self.assertEqual(expected, context_of(resolve(spdx, None)).key)

    def test_an_unknown_id_without_inline_rights_is_unknown(self):
        self.assertIsNone(resolve("Not-A-Real-Licence-9.9", None))
        self.assertEqual("unknown", context_of(None).key)


class TestExpressions(unittest.TestCase):
    def test_each_expression_derives_its_expected_context(self):
        for expression, expected in EXPECTED_EXPRESSION.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, context_of(resolve(expression, None)).key)

    def test_and_takes_the_strictest_duty_of_either_side(self):
        folded = resolve("MIT AND AGPL-3.0-only", None)
        self.assertTrue(folded["network_use_disclose"])
        self.assertTrue(folded["include_copyright"])

    def test_or_keeps_one_whole_licence_rather_than_mixing_fields(self):
        chosen = resolve("AGPL-3.0-only OR LicenseRef-RSALv2 OR SSPL-1.0", None)
        self.assertEqual(chosen, table()["AGPL-3.0-only"])

    def test_an_expression_naming_one_unknown_id_falls_back_to_inline_rights(self):
        inline = dict.fromkeys((*FIELDS, "open_source"), False)
        inline["commercial_use"] = True
        inline["modifications"] = True
        self.assertEqual(
            "source-available",
            context_of(resolve("LicenseRef-Probe-EULA", inline)).key,
        )


if __name__ == "__main__":
    unittest.main()

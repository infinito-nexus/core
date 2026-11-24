from __future__ import annotations

import unittest

from .test_spec_secrets_helper import load_helper

PADDED = (
    "hunter2  ",
    " hunter2 ",
    "hunter2\N{SOFT HYPHEN}\N{SOFT HYPHEN}",
    "hunter2\N{ZERO WIDTH SPACE}\N{ZERO WIDTH SPACE}",
    "hunter2\N{NO-BREAK SPACE}\N{NO-BREAK SPACE}",
    "\N{ZERO WIDTH NO-BREAK SPACE}hunter2",
)
LONG_ENOUGH = ("hunter2  x", "correct horse battery")
NORMALIZED_CHECK = 'if len(normalized(value.encode("utf-8"))) < MASK_MIN:'
RAW_CHECK = 'if len(value.encode("utf-8")) < MASK_MIN:'


def accepted(module, values: tuple[str, ...]) -> list[str]:
    """Parse one template line per value and keep the values parse takes.

    Args:
        module: the loaded helper.
        values: the values to try.

    Returns:
        The values parse accepted, in the given order.
    """
    taken = []
    for value in values:
        try:
            module.parse(f"A_KEY={value}\n")
        except module.SpecSecretsError:
            continue
        taken.append(value)
    return taken


class TestSpecSecretsNormalizedLength(unittest.TestCase):
    def test_every_padded_value_is_longer_than_the_floor_raw(self) -> None:
        module = load_helper()
        self.assertEqual(
            [value for value in PADDED if len(value.encode()) < module.MASK_MIN],
            [],
        )

    def test_a_value_short_once_normalized_is_refused(self) -> None:
        self.assertEqual(accepted(load_helper(), PADDED), [])

    def test_a_value_long_once_normalized_is_accepted(self) -> None:
        self.assertEqual(accepted(load_helper(), LONG_ENOUGH), list(LONG_ENOUGH))

    def test_every_accepted_value_yields_a_window_once_normalized(self) -> None:
        module = load_helper()
        for value in LONG_ENOUGH:
            self.assertGreaterEqual(
                len(module.normalized(value.encode())), module.MASK_MIN
            )


class TestSpecSecretsNormalizedLengthNegativeControls(unittest.TestCase):
    def test_a_parse_that_checks_the_raw_length_only_is_caught(self) -> None:
        raw = load_helper((NORMALIZED_CHECK, RAW_CHECK))
        self.assertEqual(accepted(raw, PADDED), list(PADDED))


if __name__ == "__main__":
    unittest.main()

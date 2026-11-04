"""The gateway's failures are distinguishable by type, not only by message.

A caller that cannot tell "no engine answered" from "one engine broke" either
retries a permanent failure forever or gives up on a transient one, so the
hierarchy below is part of the contract rather than an implementation detail.
"""

from __future__ import annotations

import unittest

from . import ERRORS


class HierarchyTestCase(unittest.TestCase):
    def test_every_failure_is_catchable_as_one_gateway_error(self) -> None:
        for name in ("NoBackendError", "EngineRefusedError", "MangledTermError"):
            with self.subTest(error=name):
                self.assertTrue(issubclass(getattr(ERRORS, name), ERRORS.GatewayError))

    def test_a_refused_engine_is_not_a_missing_backend(self) -> None:
        """One engine breaking must not read as the whole gateway being down."""
        self.assertFalse(issubclass(ERRORS.EngineRefusedError, ERRORS.NoBackendError))
        self.assertFalse(issubclass(ERRORS.NoBackendError, ERRORS.EngineRefusedError))

    def test_a_mangled_term_is_its_own_outcome(self) -> None:
        self.assertFalse(issubclass(ERRORS.MangledTermError, ERRORS.NoBackendError))

    def test_the_gateway_error_is_an_exception(self) -> None:
        self.assertTrue(issubclass(ERRORS.GatewayError, Exception))


if __name__ == "__main__":
    unittest.main()

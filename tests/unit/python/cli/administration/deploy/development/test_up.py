from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development import up


class TestHandler(unittest.TestCase):
    def test_the_target_is_reset_once_the_stack_is_up(self) -> None:
        events = []
        compose = MagicMock()
        compose.up.side_effect = lambda **_kwargs: events.append("up")
        with (
            patch.object(up, "ensure_binfmt"),
            patch.object(up, "_maybe_build_missing", return_value=0),
            patch.object(up, "make_compose", return_value=compose),
            patch.object(
                up,
                "reset_stack_target",
                side_effect=lambda stack: events.append(("reset", stack)),
            ),
        ):
            rc = up.handler(argparse.Namespace(when_down=False, skip_entry_init=True))

        self.assertEqual(rc, 0)
        self.assertEqual(events, ["up", ("reset", compose)])
        compose.up.assert_called_once_with(run_entry_init=False)


if __name__ == "__main__":
    unittest.main()

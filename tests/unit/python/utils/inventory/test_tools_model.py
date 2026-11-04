"""The alias the readiness probe expects is the one the lane deploys."""

from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.inventory.tools import LANE_MODEL_ALIAS, render

OLLAMA_ROLE = "svc-ai-ollama"


class TestLaneModel(unittest.TestCase):
    def test_the_rendered_inventory_pins_the_alias_the_probe_expects(self) -> None:
        """Two places name the model, and nothing else keeps them equal.

        The inventory carries the entry because that is where inventory data
        belongs, and the probe needs the bare alias before any render has
        run, because ``ensure`` asks whether the lane serves before the
        deploy that writes the rendered file. A lane serving one model while
        the probe expects another never reports ready and redeploys on every
        call.
        """
        rendered = load_yaml_any(str(render(PROJECT_ROOT, ["en"])))
        ollama = rendered["applications"][OLLAMA_ROLE]["services"]["ollama"]

        self.assertEqual(
            [LANE_MODEL_ALIAS],
            [model["alias"] for model in ollama["preload_models"]],
        )


if __name__ == "__main__":
    unittest.main()

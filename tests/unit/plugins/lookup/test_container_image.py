"""Unit tests for the container_image lookup plugin.

container_image is a thin wrapper around the `image` lookup: it forwards
terms + kwargs and wraps the resolved ref in a compose ``image: "<ref>"``
line. Resolution semantics are pinned by test_image.py.
"""

from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.container_image import LookupModule


def _run_with_ref(ref: str, terms, **kwargs) -> tuple[list[str], mock.MagicMock]:
    image_plugin = mock.MagicMock(run=mock.MagicMock(return_value=[ref]))
    with patch("plugins.lookup.container_image.lookup_loader") as loader_mock:
        loader_mock.get.return_value = image_plugin
        lm = LookupModule()
        lm._loader = mock.MagicMock()
        out = lm.run(terms, variables={"DEPLOYMENT_MODE": "compose"}, **kwargs)
    return out, image_plugin


class TestContainerImageLookup(unittest.TestCase):
    def test_wraps_resolved_ref_in_compose_image_line(self):
        out, _ = _run_with_ref(
            "mattermost/mattermost-team-edition:11.8.0",
            ["web-app-mattermost", "mattermost"],
        )
        self.assertEqual(out, ['image: "mattermost/mattermost-team-edition:11.8.0"'])

    def test_wraps_swarm_prefixed_ref(self):
        out, _ = _run_with_ref(
            "registry.example.com:5000/prom/prometheus:v3.13.1",
            ["web-app-prometheus", "prometheus"],
        )
        self.assertEqual(
            out, ['image: "registry.example.com:5000/prom/prometheus:v3.13.1"']
        )

    def test_forwards_terms_and_kwargs_to_image_lookup(self):
        terms = ["web-app-mattermost", "mattermost"]
        _, image_plugin = _run_with_ref(
            "busybox:1.36", terms, image="busybox", version="1.36", custom=True
        )
        image_plugin.run.assert_called_once_with(
            terms,
            variables={"DEPLOYMENT_MODE": "compose"},
            image="busybox",
            version="1.36",
            custom=True,
        )

    def test_propagates_image_lookup_error(self):
        image_plugin = mock.MagicMock(
            run=mock.MagicMock(side_effect=AnsibleError("boom"))
        )
        with patch("plugins.lookup.container_image.lookup_loader") as loader_mock:
            loader_mock.get.return_value = image_plugin
            lm = LookupModule()
            lm._loader = mock.MagicMock()
            with self.assertRaises(AnsibleError):
                lm.run(["web-app-mattermost", "mattermost"], variables={})


if __name__ == "__main__":
    unittest.main()

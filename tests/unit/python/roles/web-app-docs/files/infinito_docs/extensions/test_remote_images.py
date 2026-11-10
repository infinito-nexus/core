from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from docutils import nodes
from docutils.utils import new_document

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

remote_images = importlib.import_module("infinito_docs.extensions.remote_images")

BADGE = "https://img.shields.io/badge/Infinito.Nexus-%2ECloud-000000?labelColor=004B8D"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'


def _response(content_type: str, content: bytes = SVG) -> mock.Mock:
    response = mock.Mock(headers={"Content-Type": content_type}, content=content)
    response.raise_for_status.return_value = None
    return response


def _app(doctreedir: str, builder_format: str = "html") -> SimpleNamespace:
    return SimpleNamespace(
        builder=SimpleNamespace(format=builder_format),
        doctreedir=doctreedir,
        env=SimpleNamespace(images=mock.Mock()),
    )


def _page(*images: nodes.image) -> nodes.document:
    doctree = new_document("index")
    for image in images:
        reference = nodes.reference("", "", refuri="https://infinito.nexus")
        reference += image
        paragraph = nodes.paragraph()
        paragraph += reference
        doctree += paragraph
    return doctree


class TestFetchImage(unittest.TestCase):
    def test_an_svg_lands_under_a_suffix_that_names_its_type(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                remote_images.requests,
                "get",
                return_value=_response("image/svg+xml; charset=utf-8"),
            ),
        ):
            local = remote_images.fetch_image(BADGE, Path(tmp))

            self.assertEqual(local.suffix, ".svg")
            self.assertEqual(local.stat().st_size, len(SVG))

    def test_a_second_page_reuses_the_download(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                remote_images.requests, "get", return_value=_response("image/png")
            ) as get,
        ):
            first = remote_images.fetch_image(BADGE, Path(tmp))
            second = remote_images.fetch_image(BADGE, Path(tmp))

        self.assertEqual(first, second)
        get.assert_called_once()

    def test_an_answer_that_is_no_image_is_dropped(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                remote_images.requests, "get", return_value=_response("text/html")
            ),
        ):
            self.assertIsNone(remote_images.fetch_image(BADGE, Path(tmp)))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_an_unreachable_host_is_dropped(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                remote_images.requests,
                "get",
                side_effect=remote_images.requests.ConnectionError("down"),
            ),
        ):
            self.assertIsNone(remote_images.fetch_image(BADGE, Path(tmp)))


class TestLocalizeRemoteImages(unittest.TestCase):
    def test_a_remote_image_points_at_the_local_copy(self) -> None:
        image = nodes.image(uri=BADGE, alt="Infinito.Nexus", candidates={"?": BADGE})
        doctree = _page(image)
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                remote_images.requests, "get", return_value=_response("image/svg+xml")
            ),
        ):
            app = _app(tmp)
            remote_images.localize_remote_images(app, doctree, "index")

            local = image["uri"]
            self.assertTrue(local.startswith(str(Path(tmp, remote_images.CACHE_DIR))))
            self.assertTrue(Path(local).is_file())
        self.assertEqual(image["candidates"], {"*": local})
        app.env.images.add_file.assert_called_once_with("index", local)

    def test_an_image_that_cannot_be_fetched_gives_way_to_its_alt_text(self) -> None:
        doctree = _page(nodes.image(uri=BADGE, alt="Infinito.Nexus"))
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                remote_images.requests,
                "get",
                side_effect=remote_images.requests.Timeout("slow"),
            ),
        ):
            remote_images.localize_remote_images(_app(tmp), doctree, "index")

        self.assertEqual(list(doctree.findall(nodes.image)), [])
        reference = next(doctree.findall(nodes.reference))
        self.assertEqual(reference.astext(), "Infinito.Nexus")
        self.assertEqual(reference["refuri"], "https://infinito.nexus")

    def test_local_images_and_other_builders_are_left_alone(self) -> None:
        local = nodes.image(uri="_static/img/logo.png")
        remote = nodes.image(uri=BADGE)
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(remote_images.requests, "get") as get,
        ):
            remote_images.localize_remote_images(_app(tmp), _page(local), "index")
            remote_images.localize_remote_images(
                _app(tmp, builder_format="latex"), _page(remote), "index"
            )

        get.assert_not_called()
        self.assertEqual(local["uri"], "_static/img/logo.png")
        self.assertEqual(remote["uri"], BADGE)

    def test_setup_hooks_the_resolved_doctree(self) -> None:
        app = mock.Mock()

        meta = remote_images.setup(app)

        app.connect.assert_called_once_with(
            "doctree-resolved", remote_images.localize_remote_images
        )
        self.assertTrue(meta["parallel_read_safe"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

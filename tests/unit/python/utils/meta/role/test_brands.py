from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.meta.role.brands import brand_titles, is_brand, squashed


class TestIsBrand(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="infinito-brands-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _role(self, title: str, homepage: str = "", image: str = "") -> Path:
        role = self.root / f"role-{squashed(title) or 'x'}"
        (role / "meta").mkdir(parents=True)
        (role / "README.md").write_text(f"# {title}\n", encoding="utf-8")
        if homepage:
            (role / "meta" / "info.yml").write_text(
                f"homepage: {homepage}\n", encoding="utf-8"
            )
        if image:
            (role / "meta" / "services.yml").write_text(
                f"main:\n  image: {image}\n", encoding="utf-8"
            )
        return role

    def test_a_product_named_by_its_homepage_is_a_brand(self) -> None:
        role = self._role("Mastodon", homepage="https://joinmastodon.org/")

        self.assertTrue(is_brand("Mastodon", role))

    def test_a_product_named_by_its_image_is_a_brand(self) -> None:
        role = self._role("Certbot", image="certbot/certbot:latest")

        self.assertTrue(is_brand("Certbot", role))

    def test_a_descriptive_title_is_not(self) -> None:
        role = self._role("Cleanup Disc Space", homepage="https://example.org/")

        self.assertFalse(is_brand("Cleanup Disc Space", role))

    def test_the_words_may_appear_in_any_order(self) -> None:
        role = self._role("Claude Code", homepage="https://code.claude.com/")

        self.assertTrue(
            is_brand("Claude Code", role),
            "a product spells its parts either way round, so the title is "
            "matched word by word rather than as one string",
        )

    def test_a_role_naming_no_upstream_has_no_brand(self) -> None:
        role = self._role("Backup Host Secrets")

        self.assertFalse(is_brand("Backup Host Secrets", role))

    def test_only_the_upstream_fields_are_read(self) -> None:
        role = self._role("Shell", homepage="https://example.org/")
        (role / "README.md").write_text(
            "# Shell\n\nSee https://en.wikipedia.org/wiki/Bourne_shell\n",
            encoding="utf-8",
        )

        self.assertFalse(
            is_brand("Shell", role),
            "matching every URL in the role would let a wikipedia reference "
            "turn an ordinary word into a brand",
        )

    def test_the_repository_yields_its_known_products(self) -> None:
        titles = brand_titles()

        self.assertIn("Mastodon", titles)
        self.assertIn("Nextcloud", titles)
        self.assertNotIn("Cleanup Disc Space", titles)


if __name__ == "__main__":
    unittest.main()

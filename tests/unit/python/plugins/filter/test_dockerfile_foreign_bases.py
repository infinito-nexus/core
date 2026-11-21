from __future__ import annotations

import unittest

from plugins.filter.dockerfile_foreign_bases import dockerfile_foreign_bases

DECLARED = "node:24-alpine@sha256:feb76650b7195319268c59cb2d419c732d6c499b13bf5296f16ab59eb1f0a4f3"
MOVED = "node:24-alpine@sha256:0000000000000000000000000000000000000000000000000000000000000000"
PYTHON = "python:3.13-slim@sha256:1111111111111111111111111111111111111111111111111111111111111111"


def upstream(base: str = DECLARED) -> list[str]:
    """Return Dockerfiles shaped like the three World Monitor v2.11.8 ships.

    Args:
        base: the reference every ``FROM`` line names.
    """
    return [
        (
            f"# syntax=docker/dockerfile:1\nFROM {base} AS builder\nRUN npm ci\n"
            f"FROM {base} AS runtime-deps\nCOPY --from=builder /app /app\n"
            f"FROM {base} AS final\nCOPY --from=runtime-deps /app /app\n"
        ),
        f"FROM {base} AS inventory-builder\nRUN true\nFROM {base}\n",
        f'FROM {base}\nCMD ["node", "server.js"]\n',
    ]


class TestDockerfileForeignBases(unittest.TestCase):
    def test_the_pinned_upstream_dockerfiles_build_only_on_the_declared_base(self):
        self.assertEqual(dockerfile_foreign_bases(upstream(), [DECLARED]), [])

    def test_a_moved_digest_is_named_once(self):
        self.assertEqual(dockerfile_foreign_bases(upstream(MOVED), [DECLARED]), [MOVED])

    def test_a_moved_tag_offends_although_the_digest_stays(self):
        retagged = DECLARED.replace(":24-alpine@", ":26-alpine@")
        self.assertEqual(
            dockerfile_foreign_bases(upstream(retagged), [DECLARED]), [retagged]
        )

    def test_every_declared_base_is_allowed_and_nothing_else(self):
        texts = [f"FROM {DECLARED} AS web\nFROM {PYTHON}\n", f"FROM {MOVED}\n"]
        self.assertEqual(dockerfile_foreign_bases(texts, [DECLARED, PYTHON]), [MOVED])

    def test_no_declared_base_lets_every_image_offend(self):
        self.assertEqual(dockerfile_foreign_bases(upstream(), []), [DECLARED])

    def test_own_stages_scratch_and_platform_flags_are_no_foreign_base(self):
        text = (
            f"FROM --platform=$BUILDPLATFORM {DECLARED} AS Build\n"
            "FROM build AS test\nFROM scratch\nCOPY --from=test /out /\n"
        )
        self.assertEqual(dockerfile_foreign_bases([text], [DECLARED]), [])

    def test_a_base_taken_from_a_build_argument_offends(self):
        text = f"ARG BASE={DECLARED}\nFROM ${{BASE}}\n"
        self.assertEqual(dockerfile_foreign_bases([text], [DECLARED]), ["${BASE}"])

    def test_a_continued_from_line_is_read_as_one_instruction(self):
        text = "FROM \\\n  node:26-alpine \\\n  AS builder\n"
        self.assertEqual(
            dockerfile_foreign_bases([text], [DECLARED]), ["node:26-alpine"]
        )


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

BUILD_LOOKUP_RE = re.compile(
    r"""\{\{\s*lookup\(\s*['"]template['"]\s*,\s*['"]roles/sys-svc-container/templates/build\.yml\.j2['"]\s*\)\s*\|\s*indent\(\s*4\s*\)\s*\}\}"""
)


def image_key_re(indent: str) -> re.Pattern:
    return re.compile(
        rf"^{re.escape(indent)}(image\s*:|\{{\{{\s*lookup\(\s*['\"]container_image['\"]\s*,)"
    )


def merge_key_re(indent: str) -> re.Pattern:
    # YAML merge key: "<<:"
    return re.compile(rf"^{re.escape(indent)}<<\s*:")


_JINJA_DIRECTIVE_RE = re.compile(r"^\s*\{[%#].*[%#]\}\s*$")


class TestComposeBuildTemplateRequiresImageTag(unittest.TestCase):
    """
    Verify that every roles/*/templates/compose.yml.j2 which calls:
      {{ lookup('template', 'roles/sys-svc-container/templates/build.yml.j2') | indent(4) }}
    also defines either:
      - an `image:` tag on the same indentation level, OR
      - a YAML merge key `<<:` on the same indentation level (since it may inject `image:`).
    """

    @staticmethod
    def _iter_compose_templates(repo_root: Path):
        roles_dir = repo_root / "roles"
        if not roles_dir.is_dir():
            return []
        return sorted(roles_dir.glob(f"*/{ROLE_FILE_TEMPL_COMPOSE}"))

    @staticmethod
    def _indent_len(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    @staticmethod
    def _find_block_end(lines: list[str], start_idx: int, base_indent_len: int) -> int:
        for i in range(start_idx + 1, len(lines)):
            line = lines[i]
            if not line.strip():
                continue
            if _JINJA_DIRECTIVE_RE.match(line):
                continue

            if (
                TestComposeBuildTemplateRequiresImageTag._indent_len(line)
                < base_indent_len
            ):
                return i

        return len(lines)

    @staticmethod
    def _find_service_header(
        lines: list[str], from_idx: int, props_indent_len: int
    ) -> int | None:
        for i in range(from_idx, -1, -1):
            line = lines[i]
            if not line.strip():
                continue
            if _JINJA_DIRECTIVE_RE.match(line):
                continue

            ind = TestComposeBuildTemplateRequiresImageTag._indent_len(line)
            if ind < props_indent_len and (
                line.rstrip().endswith(":")
                and (not line.lstrip().startswith(("-", "#")))
            ):
                return i
        return None

    def test_build_lookup_requires_image_or_merge_on_same_level(self):
        repo_root = PROJECT_ROOT
        compose_files = self._iter_compose_templates(repo_root)

        self.assertTrue(
            compose_files,
            f"No compose templates found under {(repo_root / 'roles').as_posix()}/*/{ROLE_FILE_TEMPL_COMPOSE}",
        )

        violations: list[str] = []

        for path in compose_files:
            text = read_text(str(path))
            if not BUILD_LOOKUP_RE.search(text):
                continue

            lines = text.splitlines()
            checked_services: set[tuple[int, int]] = (
                set()
            )  # (header_idx, props_indent_len)

            for idx, line in enumerate(lines):
                if not BUILD_LOOKUP_RE.search(line):
                    continue

                props_indent = line[: len(line) - len(line.lstrip(" "))]
                props_indent_len = len(props_indent)

                header_idx = self._find_service_header(lines, idx, props_indent_len)
                if header_idx is None:
                    rel = path.relative_to(repo_root)
                    violations.append(
                        f"{rel}:{idx + 1} -> build.yml.j2 lookup present, but could not determine the enclosing service block."
                    )
                    continue

                key = (header_idx, props_indent_len)
                if key in checked_services:
                    continue
                checked_services.add(key)

                service_base_indent_len = self._indent_len(lines[header_idx])
                block_end = self._find_block_end(
                    lines, header_idx, service_base_indent_len
                )

                img_re = image_key_re(props_indent)
                mrg_re = merge_key_re(props_indent)

                # Search the whole service block (from header to end)
                has_image = any(
                    img_re.match(lines[j]) for j in range(header_idx + 1, block_end)
                )
                has_merge = any(
                    mrg_re.match(lines[j]) for j in range(header_idx + 1, block_end)
                )

                if not (has_image or has_merge):
                    rel = path.relative_to(repo_root)
                    violations.append(
                        f"{rel}:{idx + 1} -> build.yml.j2 lookup present, but neither 'image:' nor '<<:' found at indent level {props_indent_len} in the same service block."
                    )

        if violations:
            msg = (
                "Found compose.yml.j2 templates that include build.yml.j2 but miss 'image:' (or YAML merge '<<:') on the same level:\n"
                + "\n".join(f"- {v}" for v in violations)
            )
            self.fail(msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)

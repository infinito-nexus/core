import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT


class TestJinjaIncludePaths(unittest.TestCase):
    """
    Verifies that in all .j2 files in the project (root + subfolders):
    - Every {% include 'string/path' %} or {% include "string/path" %} refers to an existing file.
    - Any include using a variable or concatenation is ignored.
    - Includes are resolved relative to project root, template directory, or file's parent.
    """

    INCLUDE_STMT_RE = re.compile(r"{%\s*include\s+(.+?)\s*%}")
    LITERAL_PATH_RE = re.compile(r"^[\'\"]([^\'\"]+)[\'\"]$")

    def test_all_jinja_includes_exist(self):
        template_paths = list(PROJECT_ROOT.glob("**/*.j2"))
        self.assertTrue(
            template_paths, "No .j2 templates found anywhere in the project"
        )

        missing = []
        for tpl in template_paths:
            text = read_text(str(tpl))
            for stmt in self.INCLUDE_STMT_RE.finditer(text):
                expr = stmt.group(1).strip()
                m = self.LITERAL_PATH_RE.match(expr)
                if not m:
                    continue  # ignore variable-based includes

                include_path = m.group(1)
                # check absolute project-relative path
                abs_target = PROJECT_ROOT / include_path
                # check path relative to the template file
                rel_target = tpl.parent / include_path

                # check path relative to role's templates directory
                role_templates_root = None
                for parent in tpl.parents:
                    if parent.name == "templates":
                        role_templates_root = parent
                        break
                role_target = None
                if role_templates_root:
                    role_target = role_templates_root / include_path

                if not (
                    abs_target.exists()
                    or rel_target.exists()
                    or (role_target and role_target.exists())
                ):
                    rel_tpl = tpl.relative_to(PROJECT_ROOT)
                    missing.append(
                        f"{rel_tpl}: included file '{include_path}' not found "
                        f"(checked in project root, {tpl.parent.relative_to(PROJECT_ROOT)} or templates folder)"
                    )

        if missing:
            self.fail("Broken {% include %} references:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()

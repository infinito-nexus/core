import unittest

from jinja2 import Environment, exceptions, select_autoescape

from utils.cache.files import iter_project_files_with_content


class TestJinja2Syntax(unittest.TestCase):
    def test_all_j2_templates_have_valid_syntax(self):
        """
        Recursively find all .j2 files from the project root and try to parse them.
        A SyntaxError in any template fails the test.
        """
        env = Environment(autoescape=select_autoescape())
        failures = []

        for path, src in iter_project_files_with_content(extensions=(".j2",)):
            try:
                env.parse(src)
            except exceptions.TemplateSyntaxError as e:
                failures.append(f"{path}:{e.lineno} – {e.message}")

        if failures:
            self.fail(
                "Syntax errors found in Jinja2 templates:\n" + "\n".join(failures)
            )


if __name__ == "__main__":
    unittest.main()

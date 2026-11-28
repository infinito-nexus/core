from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLE = PROJECT_ROOT / "roles" / "web-app-mediawiki"
JINJA = re.compile(r"\{%.*?%\}|\{#.*?#\}|\{\{.*?\}\}", re.DOTALL)
ASSIGNMENT = re.compile(r'^\s*(\$\w+)\s*=\s*"([^"]*)";', re.MULTILINE)
SYNTAX = re.compile(r"[{};]|wfLoadExtension\(\s*'([^']+)'\s*\)")
COMPOSER_AUTOLOADED = {
    "OpenIDConnect": "oidc.php.j2",
    "AWS": "LocalSettings.php.j2",
    "VisualEditorPlus": "LocalSettings.php.j2",
}


def _guards(template: str) -> dict[str, str]:
    """
    Args:
        template: file name of a PHP template under the role's templates/.

    Returns:
        every extension the template loads, mapped to the conditions of the
        blocks around its wfLoadExtension call, with the template's string
        variables written out.
    """
    php = JINJA.sub("", read_text(str(ROLE / "templates" / template)))
    variables = dict(ASSIGNMENT.findall(php))
    loads: dict[str, str] = {}
    headers: list[str] = []
    start = 0
    for match in SYNTAX.finditer(php):
        symbol = match.group(0)
        if match.group(1):
            loads[match.group(1)] = " ".join(headers)
            continue
        if symbol == "{":
            headers.append(php[start : match.start()])
        elif symbol == "}":
            headers.pop()
        start = match.end()
    for name, value in variables.items():
        pattern = re.compile(re.escape(name) + r"(?!\w)")
        loads = {
            ext: pattern.sub(lambda _match, value=value: f'"{value}"', guard)
            for ext, guard in loads.items()
        }
    return loads


class TestComposerAutoloaderGate(unittest.TestCase):
    def test_composer_autoloaded_extensions_wait_for_their_vendor_tree(self) -> None:  # nocheck: test.text-presence -- parses the PHP block nesting around each extension load  # fmt: skip
        for extension, template in COMPOSER_AUTOLOADED.items():
            with self.subTest(extension=extension):
                guard = _guards(template)[extension]
                self.assertRegex(
                    guard,
                    rf'file_exists\(\s*"\$IP/extensions/{extension}/vendor/autoload\.php"\s*\)',
                    f"{extension} declares load_composer_autoloader, and MediaWiki's "
                    "ExtensionRegistry caches per replica for a day whether its "
                    "vendor/autoload.php existed when the extension was first queued, "
                    "so loading it before composer finished leaves that replica "
                    "without the extension's composer classes",
                )


if __name__ == "__main__":
    unittest.main()

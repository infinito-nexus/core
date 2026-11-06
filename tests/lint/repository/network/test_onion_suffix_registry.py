"""Lint: code asks the network registry which network a domain belongs to.

``utils/networks/reachability.py`` is the network registry. It owns the domain
suffix of every network and answers ``network_of(domain)``. A module that tests
``.endswith('.onion')`` on its own is a second definition of the tor network,
one that the next network (``handshake`` is reserved) or a changed suffix
leaves behind without a failing test.

The registry is reached three ways: Python imports ``utils.networks.reachability``,
Ansible and Jinja use the ``network_of`` and ``network_suffix`` filters, and code
that runs inside a container receives the suffix as an argument or environment
value rendered from ``network_suffix`` (``--proxy-suffix`` of the CSP crawler,
``TOR_SMTP_RECIPIENT_SUFFIX`` of the Tor SMTP gateway).

Scope: ``.py``, ``.yml``, ``.yaml``, ``.sh`` and ``.j2`` files under
``plugins/``, ``utils/``, ``cli/``, ``group_vars/``, ``roles/`` and ``tasks/``,
the registry itself excluded. Plain ``.js``, ``.php``, ``.rb`` and ``.lua``
files and everything under ``scripts/`` are not scanned. The checks there stay
open under requirement 055 :91 until the operator decides the migration scope:
``logout-panel.js:78`` of web-app-keycloak,
``doorkeeper_allow_onion_redirect.rb:7`` of web-app-nextcloud,
``infinito-http-onion-socks.php:21`` of web-app-wordpress, ``Keycloak.php:613``
of web-app-joomla, ``scripts/tests/e2e/onion.sh:23`` and ``rerun-spec.sh:123``.

A check is one of these regex shapes, matched in any letter case:
``endswith`` and its relatives (``ends_with``, ``end_with?``, ``endsWith``,
``removesuffix``) or ``includes``/``contains`` with the quoted suffix; a quoted
``'.onion'`` in an ``in`` test, a comparison or a tuple, list or set element; an
escaped or bracketed regex on the suffix, a pattern ending in ``onion$`` and a
SQL ``LIKE '%.onion'``; a constant or list item that holds the suffix; a
``*_SUFFIX``/``*_DOMAIN``/``*_TLD`` constant or a ``covers``/``endswith`` call
with the dotless label; a comparison with ``'onion'`` on a line that names no
route (the egress route value ``onion`` is not the suffix); ``'onion' in
<x>.split(``; a quoted ``"*.onion"`` and the shell globs ``== *.onion`` and
``*.onion)``. A shape that needs a parser, such as a split label taken through
a variable or a YAML data key called ``name`` that holds a check, is not seen.

Comments and prose are not checks. Python is read with ``tokenize``: comments
are dropped, and so are strings that contain whitespace, unless they carry Jinja
or name ``onion`` beside a comparison operator, ``search(``, ``match(``,
``LIKE`` or ``*.onion``. A bare quote does not keep a string, because messages
quote the suffix (``"'.onion' in direct.include ..."``), and a verbose regex
with spaces inside a Python string is not seen. ``#`` comments outside
quotes are dropped in YAML, shell and configuration templates only, so the Lua
length operator ``#host`` stays code. ``{# #}`` comments are always dropped, and
so are the values of the YAML prose keys (``name``, ``msg``, ``fail_msg``,
``success_msg``, ``description``) apart from the Jinja inside them. The patterns
then run over the whole file, so a call that black splits over several lines is
still seen.
"""

from __future__ import annotations

import io
import re
import tokenize
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_non_ignored_files, read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_REGISTRY = "utils/networks/reachability.py"
_ROOTS = ("plugins/", "utils/", "cli/", "group_vars/", "roles/", "tasks/")
_EXTENSIONS = (".py", ".yml", ".yaml", ".j2", ".sh")

_DOTTED = r"""['"]\.onion['"]"""
_DOTLESS = r"""['"]onion['"]"""
_CHECKS = tuple(
    re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    for pattern in (
        rf"(?:endswith|ends_with|end_with\?|endsWith|removesuffix)\s*\([^)]*?{_DOTTED}",
        rf"\b(?:includes|contains)\s*\(\s*{_DOTTED}",
        rf"{_DOTTED}\s+(?:not\s+)?in\b",
        rf"[=!]==?\s*{_DOTTED}|{_DOTTED}\s*[=!]==?",
        rf"[(\[{{,]\s*{_DOTTED}\s*[,)\]}}]",
        r"(?:\\{1,2}\.|\[\.\])onion\b",
        r"""['"][^'"\s]*onion\$""",
        r"""\bLIKE\s+['"]%\.onion['"]""",
        r"""^[ \t]*(?:-[ \t]*)?(?:[A-Za-z_][\w.-]*[ \t]*[:=][ \t]*)?['"]?\.onion['"]?[ \t]*,?[ \t]*$""",
        rf"^[ \t]*-?[ \t]*[A-Za-z_]\w*(?:suffix|domain|tld)\w*[ \t]*[:=][ \t]*{_DOTLESS}",
        rf"\b(?:endswith|ends_with|covers)\s*\(\s*{_DOTLESS}",
        rf"{_DOTLESS}\s+(?:not\s+)?in\s+[\w.()]*split\(",
        r"""['"]\*\.onion['"]""",
        r"""[=!]=\s*["']?\*\.onion\b""",
        r"(?:^|[ \t(|])\*\.onion[ \t]*[|)]",
    )
)
_DOTLESS_COMPARE = re.compile(
    rf"[=!]==?\s*{_DOTLESS}|{_DOTLESS}\s*[=!]==?", re.IGNORECASE | re.MULTILINE
)
_ROUTE = re.compile(r"route", re.IGNORECASE)
_PROSE_KEY = re.compile(
    r"^(?P<indent>\s*(?:-\s+)?)(?:name|msg|fail_msg|success_msg|description)\s*:(?P<value>.*)$"
)
_BLOCK_SCALAR = re.compile(r"^\s*[>|][-+]?\s*$")
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")
_PYTHON_STRINGS = {"STRING", "FSTRING_MIDDLE", "TSTRING_MIDDLE"}
_SCANNED_PROSE = re.compile(
    r"[=!]=|\b(?:search|match)\s*\(|\bLIKE\b|\*\.onion",
    re.IGNORECASE,
)
_YAML_TYPES = (".yml", ".yaml", ".yml.j2", ".yaml.j2")
_HASH_COMMENT_TYPES = (".yml", ".yaml", ".sh", ".py")
_HASH_COMMENT_TEMPLATES = ("", ".yml", ".yaml", ".sh", ".conf", ".cfg", ".ini", ".env")


def _blank(text: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in text)


def _jinja_only(text: str) -> str:
    kept = [" "] * len(text)
    for match in _JINJA.finditer(text):
        kept[match.start() : match.end()] = match.group()
    return "".join(kept)


def _python_code(text: str) -> str | None:
    lines = text.splitlines(keepends=True)
    blanked = [list(line) for line in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    for token in tokens:
        kind = tokenize.tok_name[token.type]
        if kind == "COMMENT":
            drop = True
        elif kind in _PYTHON_STRINGS:
            drop = bool(re.search(r"\s", token.string)) and not (
                _JINJA.search(token.string)
                or (
                    "onion" in token.string.lower()
                    and _SCANNED_PROSE.search(token.string)
                )
            )
        else:
            drop = False
        if not drop:
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            chars = blanked[row - 1]
            first = start_col if row == start_row else 0
            last = end_col if row == end_row else len(chars)
            for col in range(first, last):
                if chars[col] != "\n":
                    chars[col] = " "
    return "".join("".join(chars) for chars in blanked)


def _without_jinja_comments(text: str) -> str:
    parts = []
    position = 0
    while (start := text.find("{#", position)) != -1:
        end = text.find("#}", start + 2)
        end = len(text) if end == -1 else end + 2
        parts.append(text[position:start])
        parts.append(_blank(text[start:end]))
        position = end
    parts.append(text[position:])
    return "".join(parts)


def _without_hash_comment(line: str) -> str:
    quote = ""
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quote:
            if char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index] + " " * (len(line) - index)
    return line


def _markup_code(text: str, yaml: bool, hash_comments: bool) -> str:
    lines = _without_jinja_comments(text).split("\n")
    if hash_comments:
        lines = [_without_hash_comment(line) for line in lines]
    if not yaml:
        return "\n".join(lines)
    code = []
    prose_indent = -1
    for line in lines:
        indent = len(line) - len(line.lstrip())
        if prose_indent >= 0 and (not line.strip() or indent > prose_indent):
            code.append(_jinja_only(line))
            continue
        prose_indent = -1
        match = _PROSE_KEY.match(line)
        if match is None:
            code.append(line)
            continue
        value_start = match.start("value")
        code.append(line[:value_start] + _jinja_only(match.group("value")))
        if _BLOCK_SCALAR.match(match.group("value")):
            prose_indent = len(match.group("indent"))
    return "\n".join(code)


def code_of(text: str, extension: str) -> str:
    """Return ``text`` with comments and prose blanked, line breaks kept.

    Args:
        text: the content of one file.
        extension: the file's type as ``_extension`` names it, e.g. ``.py``,
            ``.yml``, ``.conf.j2``, ``.lua.j2`` or ``.j2`` for a template with
            no inner suffix.
    """
    if extension == ".py":
        code = _python_code(text)
        if code is not None:
            return code
    hash_comments = extension in _HASH_COMMENT_TYPES or (
        extension.endswith(".j2") and extension[:-3] in _HASH_COMMENT_TEMPLATES
    )
    return _markup_code(
        text, yaml=extension in _YAML_TYPES, hash_comments=hash_comments
    )


def suffix_checks(text: str, extension: str) -> list[int]:
    """Return the line numbers at which ``text`` tests or defines the onion suffix.

    Args:
        text: the content of one file.
        extension: see ``code_of``.
    """
    code = code_of(text, extension)
    lines = code.split("\n")
    found = {
        code.count("\n", 0, match.start()) + 1
        for pattern in _CHECKS
        for match in pattern.finditer(code)
    }
    for match in _DOTLESS_COMPARE.finditer(code):
        number = code.count("\n", 0, match.start()) + 1
        if not _ROUTE.search(lines[number - 1]):
            found.add(number)
    return sorted(found)


def _extension(path: str) -> str:
    name = Path(path).name
    if name.endswith(".j2"):
        return Path(name.removesuffix(".j2")).suffix + ".j2"
    return Path(path).suffix


def _scan_targets() -> list[str]:
    targets = []
    for path_str in iter_non_ignored_files(extensions=_EXTENSIONS, exclude_tests=True):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if rel != _REGISTRY and rel.startswith(_ROOTS):
            targets.append(path_str)
    return sorted(targets)


class TestOnionSuffixRegistry(unittest.TestCase):
    def test_the_scan_reaches_the_former_call_sites(self) -> None:
        targets = {
            Path(path).relative_to(PROJECT_ROOT).as_posix() for path in _scan_targets()
        }
        for rel in (
            "utils/preflight/domains.py",
            "utils/networks/tor_egress.py",
            (Path("roles") / "web-app-matrix" / ROLE_FILE_VARS_MAIN).as_posix(),
            "roles/sys-svc-mail-msmtp/templates/msmtprc.conf.j2",
            "roles/web-app-stalwart/tasks/14_onion_route.yml",
            "tasks/stages/01_constructor.yml",
        ):
            with self.subTest(rel=rel):
                self.assertIn(rel, targets)
        self.assertNotIn(_REGISTRY, targets)

    def test_no_module_tests_the_onion_suffix_itself(self) -> None:
        findings = []
        for path_str in _scan_targets():
            text = read_text(path_str)
            if "onion" not in text.lower():
                continue
            lines = text.splitlines()
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            findings.extend(
                f"- {rel}:{number}: {lines[number - 1].strip()}"
                for number in suffix_checks(text, _extension(path_str))
            )
        self.assertEqual(
            [],
            findings,
            "These lines test the onion suffix themselves instead of asking the "
            f"network registry ({_REGISTRY}).\n\n"
            "  Python:     network_of(domain) == TOR, network(TOR).suffix\n"
            "  Jinja:      (domain | network_of) == 'tor', 'tor' | network_suffix\n"
            "  container:  hand the suffix in, rendered from network_suffix\n",
        )

    def test_the_scan_catches_every_check_shape(self) -> None:
        caught = (
            (".py", "if host.endswith('.onion'):"),
            (".py", 'if host.endswith((".onion", ".i2p")):'),
            (".py", 'if host.endswith((".i2p", ".onion")):'),
            (".py", "if host.endswith('.ONION'):"),
            (".py", "if str.endswith(host, '.onion'):"),
            (".py", 'if host.endswith(\n    ".onion"\n):'),
            (".py", 'SUFFIXES = (\n    ".i2p",\n    ".onion",\n)'),
            (".py", "if host[-6:] == '.onion':"),
            (".py", "if host.rsplit('.', 1)[-1] == 'onion':"),
            (".py", 'ONION_DOMAIN = "onion"'),
            (".py", "    if '.onion' in host:"),
            (".py", "    if '.onion' not in host:"),
            (".py", 'ONION_SUFFIX = ".onion"'),
            (".py", 'PATTERN = re.compile(r"\\.onion(:\\d+)?/")'),
            (".yml", "X: \"{{ lookup('domain', app).endswith('.onion') }}\""),
            (".yml", "X: \"{{ host is search('\\\\.onion$') }}\""),
            (".yml", "X: \"{{ host is search('[.]onion$') }}\""),
            (".yml", "when: host is match('.*\\\\.onion')"),
            (".yml", "X: \"{{ url | regex_search('\\\\.onion(:\\\\d+)?/') }}\""),
            (".yml", "X: \"{{ hosts | select('search', 'onion$') | list }}\""),
            (".yml", "    - not (DOMAIN_PRIMARY is search('\\.onion$'))"),
            (".yml", "    if: \"ends_with(rcpt_domain, '.onion')\""),
            (".yml", "ONION_SUFFIX: '.onion'"),
            (".yml", "suffix: .onion"),
            (".yml", '- name: "Skip it"\n  when: "\'.onion\' in host"'),
            (".yml", "- name: \"Probe {{ host.endswith('.onion') }}\""),
            (".j2", "{% if host[-6:] == '.onion' %}"),
            (".j2", "  $s = str_ends_with($host, '.onion') ? 'http' : 'https';"),
            (".j2", "  if preg_match('/\\.onion$/i', $host) === 1 {"),
            (".j2", '  if (window.location.hostname.slice(-6) === ".onion") {'),
            (".j2", '  return false if uri.host.to_s.downcase.end_with?(".onion")'),
            (".sh", '  sed -i \'s|x|!url.includes(".onion")|\' "$bundle"'),
            (".sh", "  sed -i 's|a #b|x.includes(\".onion\")|' f"),
            (".sh", 'if [[ "${ONION_HOST}" != *.onion ]]; then'),
            (".sh", "  *.onion) proxy=1 ;;"),
            (".sh", "  *.onion|*.exit) proxy=1 ;;"),
            (".sh", "  *.exit|*.onion) proxy=1 ;;"),
            (
                ".yml",
                "- name: >-\n    Skip the DNS probe\n  when: host is search('\\.onion$')\n",
            ),
            (
                ".yml",
                (
                    "- name: |\n    Route\n  ansible.builtin.shell: |\n"
                    '    case "$h" in\n      *.onion) exit 0 ;;\n    esac\n'
                ),
            ),
            (
                ".yml",
                "    - name: >-\n        Probe\n      when: \"'.onion' in host\"\n",
            ),
            (".py", 'SUFFIXES = (".i2p", ".onion")'),
            (".py", 'TOR_SUFFIXES = {".onion"}'),
            (".py", 'if fnmatch.fnmatch(host, "*.onion"):'),
            (".py", 'if "onion" == labels[-1]:'),
            (".py", 'if tld == "onion":'),
            (".py", 'if host.rpartition(".")[2] == "onion":'),
            (".py", 'if "onion" in host.split("."):'),
            (".py", 'if host.removesuffix(".onion") != host:'),
            (".py", "cond = \"host is search('[.]onion$')\""),
            (
                ".py",
                'subprocess.run(["sh", "-c", "case $h in *.onion) exit 0;; esac"])',
            ),
            (".py", "q = \"SELECT 1 WHERE host LIKE '%.onion'\""),
            (".yml", "X: \"{{ (host.split('.') | last) == 'onion' }}\""),
            (".yml", "X: \"{{ 'onion' in host.split('.') }}\""),
            (".yml", "X: \"{{ host | regex_replace('^.*[.]', '') == 'onion' }}\""),
            (".lua.j2", 'if #host > 6 and host:sub(-6) == ".onion" then'),
        )
        for extension, text in caught:
            with self.subTest(extension=extension, caught=text):
                self.assertTrue(
                    suffix_checks(text, extension), f"must be reported: {text}"
                )

    def test_the_scan_names_the_line_of_a_split_call(self) -> None:
        text = 'import os\n\nif host.endswith(\n    ".onion"\n):\n    pass\n'
        self.assertIn(3, suffix_checks(text, ".py"))

    def test_the_scan_names_the_line_after_a_blank_one(self) -> None:
        cases = (
            (".py", 'import os\n\nONION_DOMAIN = "onion"\n', [3]),
            (".py", 'import os\n\nONION_SUFFIX = ".onion"\n', [3]),
            (".sh", 'case "$h" in\n\n*.onion) x ;;\nesac\n', [3]),
        )
        for extension, text, lines in cases:
            with self.subTest(text=text):
                self.assertEqual(suffix_checks(text, extension), lines)

    def test_the_scan_leaves_prose_and_registry_reads_alone(self) -> None:
        ignored = (
            (
                ".py",
                "# A .onion peer has no route off the node, so it ends with('.onion')",
            ),
            (".py", 'x = 1  # host.endswith(".onion") was the old check'),
            (".py", '    """Hosts matching ``\\.onion$`` go through Tor."""'),
            (
                ".py",
                "    raise ValueError(\"'.onion' in direct.include can never be direct\")",
            ),
            (
                ".py",
                '        f"{entry.raw!r} cannot be reached directly: .onion only exists inside Tor"',
            ),
            (".py", "    return encoded.decode('ascii').lower() + '.onion'"),
            (".py", 'ROUTE_ONION = "onion"'),
            (
                ".py",
                "ONION_DOMAIN = reachability.network(reachability.TOR).suffix.removeprefix('.')",
            ),
            (".j2", "{# routes '.onion' in the old way #}"),
            (".j2", "{#\n  multi-line: host.endswith('.onion')\n#}"),
            (
                ".j2",
                "AutomapHostsSuffixes {{ '.' if TOR_EGRESS_PLAN.automap_all else '.onion' }}",
            ),
            (".j2", "server=127.0.0.1#9053"),
            (
                ".yml",
                '- name: "🧅 Route .onion recipients through the Tor SMTP gateway"',
            ),
            (".yml", "- name: \"Skip '.onion' in the DNS pre-flight\""),
            (
                ".yml",
                "    fail_msg: \"'.onion' in direct.include can never be direct\"",
            ),
            (
                ".yml",
                (
                    "    fail_msg: >-\n      '.onion' in direct.include can never be direct,\n"
                    "      and host.endswith('.onion') is the registry's job\n    quiet: true"
                ),
            ),
            (".yml", "X: \"{{ (lookup('domain', app) | network_of) == 'tor' }}\""),
            (
                ".yml",
                "    if: \"ends_with(rcpt_domain, '{{ 'tor' | network_suffix }}')\"",
            ),
            (".yml", "    when: TOR_EGRESS_ROUTE == 'onion'"),
            (".py", 'if route == "onion":'),
            (".sh", 'echo "route onion" # host == *.onion'),
            (".conf.j2", "server=127.0.0.1 # host == '.onion' was the old rule"),
            (
                ".yml",
                (
                    "- name: >-\n    Skip '.onion' in the DNS probe\n"
                    "  when: TOR_EGRESS_ROUTE == 'all'\n"
                ),
            ),
            (
                ".yml",
                (
                    "- name: |\n    Route '.onion' in order\n"
                    "  ansible.builtin.shell: |\n    echo ok\n"
                ),
            ),
            (
                ".yml",
                "    - name: >-\n        Probe '.onion' in host\n      when: IS_COMPOSE_MODE\n",
            ),
            (
                ".py",
                'raise ValueError("a tor-listed .onion host stays in tor.include")',
            ),
        )
        for extension, text in ignored:
            with self.subTest(extension=extension, ignored=text):
                self.assertEqual(
                    suffix_checks(text, extension), [], f"must not be reported: {text}"
                )


if __name__ == "__main__":
    unittest.main()

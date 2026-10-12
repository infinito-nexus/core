"""Lint guard: a known memory parameter MUST follow the container's memory limit.

A heap, a cache size or a per-request limit written as a literal drifts away
from the ``mem_limit`` its service declares in ``meta/services.yml``: raising
the limit leaves the parameter behind, lowering it lets the process outgrow its
container. Every parameter in ``PARAMETERS`` therefore has to reach
``lookup('service_memory_mb', ...)``, or ``lookup('node_max_old_space_size', ...)``
for the V8 heap.

The lookup may sit on the parameter's own line or behind the variables its value
reads. A value reads the names inside its ``{{ }}`` expressions, apart from string
literals, attribute access and filters, and its ``$NAME`` / ``${NAME}`` shell
references. Indirection is followed inside the role and ``group_vars``: a name
counts when one of its definitions (``NAME: value``, ``NAME=value``,
``{% set NAME = value %}``) reaches the lookup, however many names lie between.
A value that keeps a literal fallback (``${NAME:-512M}``, ``... else 512``,
``default(512)``) does not count.

Only a value that starts like a size is a parameter: a digit, ``{{`` or ``$``.
That leaves prose, probes and the unlimited markers ``-1`` and ``0`` alone. A
block list under ``command:``, ``entrypoint:``, ``argv:``, ``args:`` or ``cmd:``,
a folded scalar, a backslash continuation and an expression wrapped over several
lines are each read as one line, so a flag and its value may be apart.

A sidecar snippet (``roles/<role>/templates/service.yml.j2``) runs in another
role's stack. Its lookups MUST pass ``provider='<role>'``, which keeps the size of
an engine from following the limit of the application it sits beside.

The scan knows the spellings in ``PARAMETERS`` and the layouts above. A parameter
written another way is not seen; add its spelling when a role introduces one.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from bisect import bisect_right
from collections import defaultdict
from functools import cache
from typing import TYPE_CHECKING, ClassVar

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

_SEPARATOR = r"""[\]"']*\s*(?:=>?|:|,)?\s*(?:>[+-]?\s+)?(?:value:\s*)?["'\s]*"""
PARAMETERS = (
    r"-Xm[snx]",
    r"-XX:(?:Max|Initial)HeapSize=",
    r"-XX:MaxDirectMemorySize=",
    r"\b\w*HEAP_SIZE" + _SEPARATOR,
    r"\b\w*M(?:AX|IN)(?:IMUM)?_MEMORY" + _SEPARATOR,
    r"(?i:memory[-_]limit)" + _SEPARATOR,
    r"\bwgMemoryLimit" + _SEPARATOR,
    r"(?i:memory_consumption)" + _SEPARATOR,
    r"\bLDAP_MEM_LIM" + _SEPARATOR,
    r"\blimit[-_]memory[-_](?:hard|soft)" + _SEPARATOR,
    r"\bmaxmemory" + _SEPARATOR,
    r"\bmemcached\b[^&|;]*?[\s\"']-m" + _SEPARATOR,
    r"(?<![A-Za-z])(?:shared_buffers|work_mem|effective_cache_size|wal_buffers)"
    + _SEPARATOR,
    r"\binnodb[-_]buffer[-_]pool[-_]size" + _SEPARATOR,
    r"--max[-_]old[-_]space[-_]size" + _SEPARATOR,
)

_PARAMETER = re.compile(
    "(?:"
    + "|".join(PARAMETERS)
    + r")(?P<value>(?=\d|\{\{|\$)(?:\{\{.*?\}\}|\$\{[^}]*\}|\S)+)"
)
_UNLIMITED = re.compile(r"0(?![\w.])")
_LOOKUP = re.compile(
    r"(?:lookup|query)\(\s*['\"](?:service_memory_mb|node_max_old_space_size)['\"]"
)
_FALLBACK = re.compile(r"\$\{\w+:-\s*[\"']?\d|\belse\s+[\"']?\d|\bdefault\(\s*[\"']?\d")
_EXPRESSION = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_NOT_A_NAME = re.compile(r"'[^']*'|\"[^\"]*\"|\.\s*[A-Za-z_]\w*|\|\s*[A-Za-z_]\w*")
_NAME = re.compile(r"[A-Za-z_]\w*")
_SHELL_NAME = re.compile(r"\$\{?([A-Za-z_]\w*)")
_DEFINITION = re.compile(
    r"^\s*(?:-\s+)?(?:(?:export|local|readonly|ARG|ENV)\s+)?"
    r"[\"']?([A-Za-z_]\w*)[\"']?\s*(?::(?=\s|$)|=)(.*)$"
)
_JINJA_SET = re.compile(r"\{%-?\s*set\s+(\w+)\s*=(.*?)-?%\}")
_BLOCK_SCALAR = re.compile(r"[>|][+-]?\d*")
_ARGV_KEY = re.compile(r"^\s*(?:-\s+)?(?:command|entrypoint|argv|args|cmd)\s*:\s*$")
_FOLDED = re.compile(r":\s*>[+-]?\d*\s*$")
_ITEM = re.compile(r"^\s*-\s+")
_TRAILING_COMMENT = re.compile(r"\s#.*$")
_SIDECAR = re.compile(r"roles/([^/]+)/templates/service\.yml\.j2")
_SIZING = re.compile(r"lookup\(\s*['\"]service_memory_mb['\"][^)]*\)")
_COMMENT = ("#", ";", "//", "{#")
_SHARED_SCOPE = "group_vars"
_WRAP = 20


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _code(lines: Sequence[str]) -> list[str]:
    return [_TRAILING_COMMENT.sub("", line) for line in lines]


def _open(lines: Sequence[str]) -> bool:
    return sum(line.count("{{") for line in lines) > sum(
        line.count("}}") for line in lines
    )


def _block_end(lines: Sequence[str], start: int) -> int:
    end = start + 1
    while end < len(lines) and (
        not lines[end].strip() or _indent(lines[end]) > _indent(lines[start])
    ):
        end += 1
    return end


def definitions(lines: Sequence[str]) -> Iterator[tuple[str, str]]:
    """Yield every ``(name, value)`` a file defines.

    Args:
        lines: the file's lines. Trailing comments are cut. A value continues over
            the deeper indented lines below its key when it is a YAML block scalar
            or leaves a ``{{`` open.
    """
    lines = _code(lines)
    for number, line in enumerate(lines):
        for name, expression in _JINJA_SET.findall(line):
            yield name, "{{" + expression + "}}"
        match = _DEFINITION.match(line)
        if not match:
            continue
        value = match[2]
        if _BLOCK_SCALAR.fullmatch(value.strip()) or _open([value]):
            value = " ".join([value, *lines[number + 1 : _block_end(lines, number)]])
        yield match[1], value


def references(value: str) -> set[str]:
    """Return the names *value* reads.

    Args:
        value: text that is rendered later. Names inside ``{{ }}`` and shell
            references count; bare words, string literals, attributes and
            filters do not.
    """
    names = set(_SHELL_NAME.findall(value))
    for expression in _EXPRESSION.findall(value):
        names.update(_NAME.findall(_NOT_A_NAME.sub(" ", expression)))
    return names


def reaches_lookup(value: str, known: Mapping[str, Sequence[str]]) -> bool:
    """Whether *value* calls the lookup itself or reads a variable that does.

    Args:
        value: the expression a parameter is set to.
        known: variable name to every value it is defined with.
    """
    pending, seen = [value], set()
    while pending:
        current = pending.pop()
        if _FALLBACK.search(current):
            continue
        if _LOOKUP.search(current):
            return True
        for name in references(current) - seen:
            seen.add(name)
            pending.extend(known.get(name, ()))
    return False


def _logical_lines(lines: Sequence[str]) -> Iterator[tuple[str, list[int], list[int]]]:
    """Yield ``(text, offsets, numbers)``: one logical line and where each source line starts in it.

    Args:
        lines: the file's lines, trailing comments already cut.
    """
    index = 0
    while index < len(lines):
        end = index + 1
        if _ARGV_KEY.match(lines[index]) or _FOLDED.search(lines[index]):
            end = _block_end(lines, index)
        while (
            end < len(lines)
            and end - index < _WRAP
            and (lines[end - 1].rstrip().endswith("\\") or _open(lines[index:end]))
        ):
            end += 1
        text, offsets, numbers = "", [], []
        for number in range(index, end):
            piece = lines[number]
            if number > index:
                piece = _ITEM.sub("", piece).strip()
                if piece.startswith(_COMMENT):
                    continue
            offsets.append(len(text))
            numbers.append(number + 1)
            text += piece.rstrip("\\") + " "
        yield text, offsets, numbers
        index = end


def parameters(text: str) -> list[tuple[int, str, str]]:
    """Return ``(line number, parameter with value, value)`` per known parameter.

    Args:
        text: a file's content. Comments and the unlimited marker ``0`` are skipped.
    """
    found = []
    for line, offsets, numbers in _logical_lines(_code(text.splitlines())):
        if line.lstrip().startswith(_COMMENT):
            continue
        for match in _PARAMETER.finditer(line):
            if not _UNLIMITED.match(match.group("value")):
                number = numbers[bisect_right(offsets, match.start()) - 1]
                found.append((number, match.group(0), match.group("value")))
    return found


def detached(text: str, known: Mapping[str, Sequence[str]]) -> list[tuple[int, str]]:
    """Return ``(line number, parameter with value)`` for every parameter that never reaches the lookup.

    Args:
        text: a file's content.
        known: variable name to every value it is defined with.
    """
    return [
        (number, parameter)
        for number, parameter, value in parameters(text)
        if not reaches_lookup(value, known)
    ]


def unprovided(rel: str, text: str) -> list[int]:
    """Return the lines of a sidecar snippet whose lookup does not name its own role as provider.

    Args:
        rel: repository-relative path of the file.
        text: its content.
    """
    sidecar = _SIDECAR.fullmatch(rel)
    if not sidecar:
        return []
    provider = re.compile(rf"provider\s*=\s*['\"]{re.escape(sidecar[1])}['\"]")
    return [
        number
        for number, line in enumerate(text.splitlines(), 1)
        for call in _SIZING.findall(line)
        if not provider.search(call)
    ]


def merged(*scopes: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """Return one name-to-values map holding every definition of every scope.

    Args:
        scopes: name-to-values maps; a name defined in several keeps all its values.
    """
    union: dict[str, list[str]] = defaultdict(list)
    for scope in scopes:
        for name, values in scope.items():
            union[name].extend(values)
    return union


def _scope(rel: str) -> str:
    parts = rel.split("/")
    return "/".join(parts[:2]) if parts[0] == "roles" else _SHARED_SCOPE


@cache
def _tracked_texts() -> dict[str, str]:
    out = subprocess.check_output(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(PROJECT_ROOT),
            "ls-files",
            "roles",
            _SHARED_SCOPE,
        ],
        text=True,
    )
    texts: dict[str, str] = {}
    for rel in out.splitlines():
        if rel.endswith(".md"):
            continue
        try:
            texts[rel] = read_text(str(PROJECT_ROOT / rel))
        except (OSError, UnicodeDecodeError):
            continue
    return texts


class TestMemoryParametersUseLookup(unittest.TestCase):
    def test_every_memory_parameter_follows_the_container_limit(self) -> None:
        texts = _tracked_texts()
        index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for rel, text in texts.items():
            for name, value in definitions(text.splitlines()):
                index[_scope(rel)][name].append(value)
        known = {
            scope: merged(*(index[name] for name in {_SHARED_SCOPE, scope}))
            for scope in list(index)
        }

        seen = 0
        offenders: list[str] = []
        for rel, text in sorted(texts.items()):
            seen += len(parameters(text))
            offenders.extend(
                f"  {rel}:{number}: {parameter}"
                for number, parameter in detached(text, known.get(_scope(rel), {}))
            )

        self.assertGreater(seen, 0, "the scan matched no memory parameter at all")
        self.assertFalse(
            offenders,
            "Memory parameters that do not follow their container's mem_limit "
            f"({len(offenders)}):\n"
            + "\n".join(offenders)
            + "\n\nSet the value with lookup('service_memory_mb', application_id, "
            "<service>, <share>), directly or through a variable of the role.",
        )

    def test_every_sidecar_lookup_names_its_provider(self) -> None:
        texts = _tracked_texts()
        sized = sum(
            len(_SIZING.findall(text))
            for rel, text in texts.items()
            if _SIDECAR.fullmatch(rel)
        )
        offenders = [
            f"  {rel}:{number}"
            for rel, text in sorted(texts.items())
            for number in unprovided(rel, text)
        ]

        self.assertGreater(sized, 0, "no sidecar snippet sizes memory with the lookup")
        self.assertFalse(
            offenders,
            "Sidecar lookups without provider='<own role>':\n" + "\n".join(offenders),
        )


class TestResolution(unittest.TestCase):
    _SIZED: ClassVar[str] = "{{ lookup('service_memory_mb', 'app', 'php', 0.5) }}"

    def test_literal_is_reported(self) -> None:
        self.assertEqual(
            detached("ES_JAVA_OPTS=-Xms512m -Xmx512m", {}),
            [(1, "-Xms512m"), (1, "-Xmx512m")],
        )

    def test_literal_next_to_a_resolved_value_is_still_reported(self) -> None:
        self.assertEqual(
            detached("ES_JAVA_OPTS=-Xms512m -Xmx{{ HEAP }}m", {"HEAP": [self._SIZED]}),
            [(1, "-Xms512m")],
        )

    def test_direct_lookup_passes(self) -> None:
        self.assertEqual(detached(f"memory_limit = {self._SIZED}M", {}), [])

    def test_chain_of_variables_passes(self) -> None:
        known = dict(
            definitions(
                [
                    'PHP_LIMIT="${INIT_LIMIT:?INIT_LIMIT must be set}"',
                    "      INIT_LIMIT: \"{{ ROLE_LIMIT ~ 'M' }}\"",
                    "ROLE_LIMIT: >-",
                    "  {{ lookup('service_memory_mb', application_id, 'init', 0.5) }}",
                ]
            )
        )
        self.assertEqual(
            detached(
                'php -d memory_limit="$PHP_LIMIT" bin/console',
                {k: [v] for k, v in known.items()},
            ),
            [],
        )

    def test_variable_that_never_reaches_the_lookup_is_reported(self) -> None:
        known = {"A": ["{{ B }}"], "B": ["{{ A }}"], "OTHER": ["512M"]}
        self.assertEqual(
            detached("--maxmemory {{ A }}mb\nshared_buffers={{ OTHER }}", known),
            [(1, "maxmemory {{ A }}mb"), (2, "shared_buffers={{ OTHER }}")],
        )

    def test_a_name_inside_a_string_literal_is_not_followed(self) -> None:
        sized = [self._SIZED]
        known = {"config": sized, "limit": sized, "int": sized, "item": ["512M"]}
        value = "{{ lookup('config', item.limit, 'php.limit') | int }}"
        self.assertEqual(
            detached(f"PHP_MEMORY_LIMIT={value}", known),
            [(1, f"MEMORY_LIMIT={value}")],
        )

    def test_a_literal_fallback_does_not_count(self) -> None:
        known = {"INIT": [self._SIZED]}
        for line in (
            'PHP_MEMORY_LIMIT="${INIT:-1024M}"',
            "-Xmx{{ INIT if swarm else 512 }}m",
            "memory_limit = {{ INIT | default(512) }}M",
        ):
            with self.subTest(line=line):
                self.assertEqual(len(detached(line, known)), 1)

    def test_a_lookup_named_in_a_comment_does_not_count(self) -> None:
        known = {
            name: [value]
            for name, value in definitions(
                ["HEAP: 1024 # lookup('service_memory_mb', ...) rounds too low"]
            )
        }
        self.assertEqual(detached("-Xmx{{ HEAP }}m", known), [(1, "-Xmx{{ HEAP }}m")])

    def test_a_role_definition_does_not_hide_the_shared_one(self) -> None:
        known = merged({"SIZE": [self._SIZED]}, {"SIZE": ["{{ SIZE }}"]})
        self.assertEqual(detached("work_mem={{ SIZE }}", known), [])

    def test_flag_and_value_apart_are_one_parameter(self) -> None:
        sized = {"SIZE": [self._SIZED]}
        for block, line in (
            (
                '  command:\n    - memcached\n    - -m\n    - "{{ SIZE }}"\n  image: x',
                2,
            ),
            (
                '  argv:\n    - redis-server\n    - "--maxmemory"\n    - "{{ SIZE }}mb"',
                3,
            ),
            ('command: ["redis-server", "--maxmemory", "{{ SIZE }}mb"]', 1),
            ("shell: >-\n  redis-server\n  --maxmemory\n  {{ SIZE }}mb", 3),
            ("exec memcached \\\n  -m {{ SIZE }} \\\n  -p 11211", 1),
        ):
            with self.subTest(block=block):
                self.assertEqual(detached(block, sized), [])
                self.assertEqual(
                    [number for number, _ in detached(block, {"SIZE": ["64"]})], [line]
                )

    def test_a_value_wrapped_over_lines_is_one_value(self) -> None:
        wrapped = (
            "X_MEMORY_LIMIT: \"{{ [ (lookup('service_memory_mb', application_id,\n"
            "  'php', 0.5) | int), 64 ] | max }}M\""
        )
        for text in (wrapped, f"X_MEMORY_LIMIT: >-\n  {self._SIZED}M"):
            with self.subTest(text=text):
                self.assertEqual(len(parameters(text)), 1)
                self.assertEqual(detached(text, {}), [])
        self.assertEqual(len(detached("X_MEMORY_LIMIT: >-\n  512M", {})), 1)

    def test_every_spelling_of_a_parameter_is_known(self) -> None:
        for line in (
            "php_admin_value[memory_limit] = 1G",
            "php_value memory_limit 512M",
            "@ini_set('memory_limit', '512M');",
            "'memory_limit' => '512M',",
            '"memory_limit": "512M",',
            '- { key: "WP_MEMORY_LIMIT", value: "256M" }',
            '$wgMemoryLimit = "512M";',
            "JVM_MAXIMUM_MEMORY: 4096m",
            "JICOFO_MAX_MEMORY=3072m",
            "ES_HEAP_SIZE=1g",
            "JAVA_OPTS=-XX:MaxHeapSize=7g",
            "JAVA_OPTS=-Xmn256m",
            "LDAP_MEM_LIM=500M",
            "    - --memory-limit=512M",
            'command: ["--memory-limit", "512M"]',
            "opcache.memory_consumption=256",
            "limit_memory_hard = 2684354560",
            "odoo --limit-memory-hard 2684354560",
            '  db_shared_buffers: "4096MB"',
            '      - "effective_cache_size=4GB"',
            '      - "--innodb-buffer-pool-size=1G"',
            "NODE_OPTIONS=--max-old-space-size=4096",
        ):
            with self.subTest(line=line):
                self.assertEqual(len(detached(line, {})), 1)

    def test_unrelated_lines_are_ignored(self) -> None:
        for line in (
            "  # -Xmx512m",
            "; memory_limit = 512M",
            "- --maxmemory-policy allkeys-lru",
            "- --maxmemory 0",
            'RUN : "${PHP_MEMORY_LIMIT:?}"',
            "bootstrap.memory_lock=true",
            "mem_limit: 2g",
            "network_mem: 512",
            "php -d memory_limit=-1 artisan migrate",
            "RUN COMPOSER_MEMORY_LIMIT=-1 composer install",
            '      - "autovacuum_work_mem=-1"',
            "retries: 3 # was php -d memory_limit=512M",
            "retries: 3 #was php -d memory_limit=512M",
            '- name: "Tune the JVM heap (-Xms/-Xmx)"',
            "php -i | grep -E '^memory_limit => '",
            'f"--max-old-space-size={megabytes}"',
            "memcached && install -m 0755 /src /dst",
        ):
            with self.subTest(line=line):
                self.assertEqual(detached(line, {}), [])


class TestSidecarProvider(unittest.TestCase):
    _SNIPPET: ClassVar[str] = "roles/svc-db-redis/templates/service.yml.j2"

    def _line(self, options: str) -> str:
        return (
            "      - --maxmemory {{ lookup('service_memory_mb', application_id, "
            f"'redis', 0.8{options}) }}}}mb"
        )

    def test_a_sidecar_lookup_without_its_own_provider_is_reported(self) -> None:
        for options in (
            "",
            ", provider='svc-db-memcached'",
            ", providr='svc-db-redis'",
        ):
            with self.subTest(options=options):
                self.assertEqual(unprovided(self._SNIPPET, self._line(options)), [1])

    def test_a_sidecar_lookup_naming_its_role_passes(self) -> None:
        line = self._line(", provider='svc-db-redis'")

        self.assertEqual(unprovided(self._SNIPPET, line), [])

    def test_other_files_are_not_sidecars(self) -> None:
        path = f"roles/svc-db-redis/{ROLE_FILE_TEMPL_COMPOSE}"

        self.assertEqual(unprovided(path, self._line("")), [])


if __name__ == "__main__":
    unittest.main()

"""Lint: no Ansible task runs an application's default database seeds.

Laravel: ``php artisan db:seed`` without ``--class`` and ``php artisan migrate
--seed`` without ``--seeder`` run ``Database\\Seeders\\DatabaseSeeder``; naming
``DatabaseSeeder`` explicitly counts too. Rails: ``rails``/``rake``
``db:seed``, ``db:seed:replant``, ``db:setup``, ``db:reset`` and ``db:prepare``
load ``db/seeds.rb``, ``db:prepare`` whenever it sets up an empty database.

A Laravel task MAY seed a named class that is safe to repeat::

    php artisan db:seed --class=Database\\Seeders\\RolesSeeder --force

A task whose own or enclosing ``when:`` carries ``MODE_DEMO | bool`` or bare
``MODE_DEMO`` as an ``and`` term, without ``or``, is allowed. A Rails task whose
seeds are safe in production carries ``# nocheck: default-seeder <reason>`` on,
or directly above, the line where its command value starts: a block scalar's
``key: >`` line, an inline string, or the first ``argv:`` item. The marker
never exempts Laravel's default seeder.

Scans every YAML file under ``roles/*/tasks/``, ``roles/*/handlers/`` and the
top-level ``tasks/``. Module arguments are read as composed YAML, so an
``argv:`` list, a folded or literal shell block and a ``set_fact`` that
assembles an argv are all covered; the task ``name`` is not.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import dump_yaml_str

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_RULE = "default-seeder"
_ARTISAN = re.compile(r"\bartisan\b")
_DB_SEED = re.compile(r"(?<![\w:-])db:seed(?![\w:-])")
_MIGRATE = re.compile(r"(?<![\w:-])migrate(?::(?:fresh|refresh))?(?![\w:-])")
_SEED_FLAG = re.compile(r"(?<![\w-])--seed(?![\w-])")
_CLASS = re.compile(r"--class(?:=|\s+)[\"']?(?P<cls>[\w\\]+)")
_SEEDER = re.compile(r"--seeder(?:=|\s+)[\"']?(?P<cls>[\w\\]+)")
_RAILS = re.compile(r"\b(?:rails|rake)\b")
_RAILS_SEED = re.compile(
    r"(?<![\w:-])db:(?:seed(?::replant)?|setup|reset|prepare)(?![\w:-])"
)
_COMMAND_SEPARATOR = re.compile(r"\n|;|&&|\|\|")
_OR = re.compile(r"\bor\b")
_AND = re.compile(r"\band\b")
_DEMO_TERM = re.compile(r"\(?\s*MODE_DEMO\s*(?:\|\s*bool\s*)?\)?")
_DEFAULT_SEEDER = "DatabaseSeeder"
_NESTED_TASK_KEYS = ("block", "rescue", "always")
_TASK_DIRS = frozenset({"tasks", "handlers"})


def _names_default_seeder(match: re.Match[str] | None) -> bool:
    """Report whether a ``--class`` / ``--seeder`` match selects the default.

    Args:
        match: the option match within one command, or ``None`` when absent.

    Returns:
        ``True`` when the option is missing or names ``DatabaseSeeder``.
    """
    return match is None or match.group("cls").split("\\")[-1] == _DEFAULT_SEEDER


def _runs_laravel_default_seeder(command: str) -> bool:
    """Report whether one shell command runs the default Laravel seeder.

    Args:
        command: a single command, already split from its neighbours.

    Returns:
        ``True`` for ``artisan db:seed`` or ``artisan migrate --seed`` that
        does not name a seeder class other than ``DatabaseSeeder``.
    """
    if not _ARTISAN.search(command):
        return False
    if _DB_SEED.search(command):
        return _names_default_seeder(_CLASS.search(command))
    if _MIGRATE.search(command) and _SEED_FLAG.search(command):
        return _names_default_seeder(_SEEDER.search(command))
    return False


def _runs_rails_seeds(command: str) -> bool:
    """Report whether one shell command loads a Rails application's seeds.

    Args:
        command: a single command, already split from its neighbours.

    Returns:
        ``True`` for a ``rails``/``rake`` call of a task that loads ``db/seeds.rb``.
    """
    return bool(_RAILS.search(command) and _RAILS_SEED.search(command))


def _runs_default_seeds(text: str, line: int, lines: Sequence[str]) -> bool:
    """Report whether one module argument runs default seeds no marker exempts.

    Args:
        text: the argument, possibly holding several shell commands.
        line: the 1-based line where the argument's value starts.
        lines: the lines of the task file.

    Returns:
        ``True`` for a Laravel default seeder, or for Rails seeds without a
        ``default-seeder`` marker on or directly above ``line``.
    """
    commands = _COMMAND_SEPARATOR.split(text.replace("\\\n", " "))
    if any(_runs_laravel_default_seeder(command) for command in commands):
        return True
    return any(_runs_rails_seeds(command) for command in commands) and not (
        is_suppressed_at(lines, line, _RULE)
    )


def _texts(node: yaml.Node) -> Iterator[tuple[str, int]]:
    """Yield the command-like strings inside a task's module arguments.

    Args:
        node: any composed YAML node of a task.

    Returns:
        An iterator over ``(text, line)`` pairs, ``line`` being the 1-based
        line where the value starts; a list of scalars is joined with spaces
        so an ``argv:`` list reads as one command.
    """
    if isinstance(node, yaml.ScalarNode):
        yield node.value, node.start_mark.line + 1
    elif isinstance(node, yaml.SequenceNode):
        if all(isinstance(item, yaml.ScalarNode) for item in node.value):
            joined = " ".join(item.value for item in node.value)
            yield joined, node.start_mark.line + 1
        else:
            for item in node.value:
                yield from _texts(item)
    elif isinstance(node, yaml.MappingNode):
        for _key, value in node.value:
            yield from _texts(value)


def _requires_demo(when: yaml.Node | None) -> bool:
    """Report whether a ``when:`` value requires ``MODE_DEMO``.

    Args:
        when: the composed ``when:`` value of a task or block, or ``None``.

    Returns:
        ``True`` when one condition without ``or`` carries ``MODE_DEMO | bool``
        or bare ``MODE_DEMO`` as one of its ``and`` terms.
    """
    if isinstance(when, yaml.ScalarNode):
        conditions = [when.value]
    elif isinstance(when, yaml.SequenceNode):
        conditions = [
            item.value for item in when.value if isinstance(item, yaml.ScalarNode)
        ]
    else:
        return False
    return any(
        not _OR.search(condition)
        and any(_DEMO_TERM.fullmatch(term.strip()) for term in _AND.split(condition))
        for condition in conditions
    )


def _offending_tasks(
    tasks: yaml.Node | None, lines: Sequence[str], gated: bool
) -> Iterator[str]:
    """Yield the name of every task that runs default seeds.

    Args:
        tasks: a composed file root or ``block``/``rescue``/``always`` value.
        lines: the lines of the task file.
        gated: whether an enclosing block's ``when:`` requires ``MODE_DEMO``.

    Returns:
        An iterator over offending task names, nested tasks included.
    """
    if not isinstance(tasks, yaml.SequenceNode):
        return
    for task in tasks.value:
        if not isinstance(task, yaml.MappingNode):
            continue
        items = {
            key.value: value
            for key, value in task.value
            if isinstance(key, yaml.ScalarNode)
        }
        task_gated = gated or _requires_demo(items.get("when"))
        for key in _NESTED_TASK_KEYS:
            yield from _offending_tasks(items.get(key), lines, task_gated)
        if task_gated:
            continue
        texts = (
            pair
            for key, value in items.items()
            if key != "name" and key not in _NESTED_TASK_KEYS
            for pair in _texts(value)
        )
        if any(_runs_default_seeds(text, line, lines) for text, line in texts):
            name = items.get("name")
            yield name.value if isinstance(name, yaml.ScalarNode) else "<unnamed>"


def _offending_task_names(content: str) -> list[str]:
    """Return the name of every task in a task file that runs default seeds.

    Args:
        content: the text of a YAML task file.

    Returns:
        The offending task names in file order.
    """
    lines = content.splitlines()
    return [
        name
        for document in yaml.compose_all(content, Loader=yaml.SafeLoader)
        for name in _offending_tasks(document, lines, gated=False)
    ]


def _is_scan_target(rel: str) -> bool:
    """Report whether a repository-relative YAML path holds Ansible tasks.

    Args:
        rel: POSIX path relative to the project root.

    Returns:
        ``True`` for the top-level ``tasks/`` tree and a role's ``tasks/`` or
        ``handlers/`` tree.
    """
    parts = rel.split("/")
    if parts[0] == "tasks":
        return True
    return parts[0] == "roles" and len(parts) > 3 and parts[2] in _TASK_DIRS


class TestNoDefaultDatabaseSeeder(unittest.TestCase):
    def _offenders(self, tasks: list[dict[str, Any]]) -> list[str]:
        return _offending_task_names(dump_yaml_str(tasks))

    def test_no_task_runs_default_seeds(self) -> None:
        offenders: list[str] = []
        for path, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"), exclude_tests=True
        ):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            if "artisan" not in content and not _RAILS_SEED.search(content):
                continue
            offenders.extend(
                f"{rel}: task '{name}'" for name in _offending_task_names(content)
            )

        self.assertFalse(
            offenders,
            "these tasks run an application's default database seeds, which "
            "upstream ships for development data and which may truncate "
            "production tables or create known logins:\n  "
            + "\n  ".join(offenders)
            + "\n\nFix: drop the seed, or gate it on `when: MODE_DEMO | bool`. "
            "Laravel: name a seeder class that is safe to repeat with "
            "`artisan db:seed --class=<Seeder>` / "
            "`artisan migrate --seed --seeder=<Seeder>`. Rails seeds verified "
            "safe in production: add `# nocheck: default-seeder <reason>` on or "
            "directly above the line where the command value starts.",
        )

    def test_detector_separates_the_laravel_default_from_named_seeders(
        self,
    ) -> None:
        flagged = (
            "php artisan db:seed --force",
            "php -d memory_limit=512M artisan db:seed --force",
            "php artisan db:seed --class=DatabaseSeeder --force",
            "php artisan db:seed --class='Database\\Seeders\\DatabaseSeeder'",
            "php artisan migrate --force --seed",
            "php artisan migrate:fresh --seed --seeder=DatabaseSeeder",
            "sh -c 'php artisan migrate --force && php artisan db:seed --force'",
            "container exec -i app \\\n  php artisan db:seed \\\n  --force",
        )
        passed = (
            "php artisan migrate --force",
            "php artisan migrate:status",
            "php artisan db:seed --class=RolesSeeder --force",
            "php artisan db:seed --class Database\\Seeders\\RolesSeeder",
            "php artisan migrate --seed --seeder=RolesSeeder",
            "php artisan migrate --force && php artisan db:seed --class=RolesSeeder",
        )
        for command in flagged:
            with self.subTest(flagged=command):
                tasks = [{"name": "t", "ansible.builtin.shell": command}]
                self.assertEqual(self._offenders(tasks), ["t"])
        for command in passed:
            with self.subTest(passed=command):
                tasks = [{"name": "t", "ansible.builtin.shell": command}]
                self.assertEqual(self._offenders(tasks), [])

    def test_detector_flags_every_rails_task_that_loads_the_seeds(self) -> None:
        flagged = (
            "bin/rails db:seed",
            "bundle exec rails db:seed",
            "RAILS_ENV=production bundle exec rake db:setup",
            "rails db:reset",
            "bin/rails db:prepare",
            "bin/rails db:seed:replant",
            "container exec cid bash -lc 'bin/rails db:migrate && bin/rails db:seed'",
        )
        passed = (
            "bundle exec rails db:migrate",
            "bin/rails db:schema:load",
            "bin/rails db:test:prepare",
            "bundle exec rails runner -",
            "npm run db:seed",
        )
        for command in flagged:
            with self.subTest(flagged=command):
                tasks = [{"name": "t", "ansible.builtin.shell": command}]
                self.assertEqual(self._offenders(tasks), ["t"])
        for command in passed:
            with self.subTest(passed=command):
                tasks = [{"name": "t", "ansible.builtin.shell": command}]
                self.assertEqual(self._offenders(tasks), [])

    def test_detector_reads_argv_lists_and_nested_blocks(self) -> None:
        laravel = ["container", "exec", "app", "php", "artisan", "db:seed", "--force"]
        rails = ["container", "exec", "cid", "bin/rails", "db:seed"]
        tasks = [
            {"name": "only the title says artisan db:seed", "debug": {"msg": "x"}},
            {"block": [{"name": "argv", "ansible.builtin.command": {"argv": laravel}}]},
            {"name": "rails", "ansible.builtin.command": {"argv": rails}},
        ]
        self.assertEqual(self._offenders(tasks), ["argv", "rails"])

    def test_a_mode_demo_gate_allows_the_default_seeds(self) -> None:
        gates = (
            "MODE_DEMO | bool",
            "MODE_DEMO|bool",
            "MODE_DEMO",
            "ENVIRONMENT == 'production' and MODE_DEMO | bool",
            ["ENVIRONMENT == 'production'", "MODE_DEMO | bool"],
        )
        for when in gates:
            with self.subTest(gated=when):
                tasks = [
                    {"name": "l", "shell": "php artisan db:seed --force", "when": when},
                    {"name": "r", "shell": "bin/rails db:seed", "when": when},
                ]
                self.assertEqual(self._offenders(tasks), [])
        block = [
            {
                "block": [{"name": "r", "shell": "bin/rails db:seed"}],
                "rescue": [{"name": "l", "shell": "php artisan db:seed --force"}],
                "when": "MODE_DEMO | bool",
            }
        ]
        self.assertEqual(self._offenders(block), [])

    def test_a_missing_or_negated_mode_demo_gate_is_flagged(self) -> None:
        gates = (
            None,
            "ENVIRONMENT == 'production'",
            "not MODE_DEMO | bool",
            "not MODE_DEMO",
            "MODE_DEMO | bool or ENVIRONMENT == 'development'",
            ["ENVIRONMENT == 'production'", "not MODE_DEMO | bool"],
        )
        for when in gates:
            with self.subTest(ungated=when):
                task: dict[str, Any] = {"name": "t", "shell": "bin/rails db:seed"}
                if when is not None:
                    task["when"] = when
                self.assertEqual(self._offenders([task]), ["t"])

    def test_a_marker_exempts_rails_seeds_only(self) -> None:
        exempt = (
            (
                "- name: t\n"
                "  # nocheck: default-seeder  seeds are find_or_create\n"
                "  ansible.builtin.shell: > # nocheck: container-exec-resolver  cid\n"
                "    container exec cid\n"
                "    bash -lc 'bin/rails db:seed'\n"
            ),
            "- name: t\n  shell: bin/rails db:seed # nocheck: default-seeder  why\n",
            (
                "- name: t\n"
                "  command:\n"
                "    argv: # nocheck: default-seeder  why\n"
                "      - bin/rails\n"
                "      - db:seed\n"
            ),
        )
        flagged = (
            (
                "- name: t\n"
                "  # nocheck: default-seeder  why\n"
                "  shell: php artisan db:seed --force\n"
            ),
            (
                "- name: t # nocheck: default-seeder  why\n"
                "  become: true\n"
                "  shell: bin/rails db:seed\n"
            ),
            (
                "- name: t\n"
                "  ansible.builtin.shell: > # nocheck: container-exec-resolver  cid\n"
                "    container exec cid\n"
                "    bash -lc 'bin/rails db:seed'\n"
            ),
        )
        for text in exempt:
            with self.subTest(exempt=text):
                self.assertEqual(_offending_task_names(text), [])
        for text in flagged:
            with self.subTest(flagged=text):
                self.assertEqual(_offending_task_names(text), ["t"])


if __name__ == "__main__":
    unittest.main()

"""Block raw YAML keys that are incompatible between docker-compose and
swarm deployment modes.

Each rule corresponds to a service-level YAML key whose semantics differ
between the two modes. Render paths must route through the appropriate
SPOT lookup (defined in `plugins/lookup/`) which suppresses or rewrites
the key per `DEPLOYMENT_MODE`.

Currently enforced rules:

* ``container-name`` -> ``compose_only('container_name', NAME)``.
  Hard-rejected in swarm when ``deploy.replicas > 1`` (deploy fails
  outright).
* ``pull-policy-key`` -> ``compose_only('pull_policy', VALUE)``.
  Swarm rejects ``pull_policy`` as "Additional property pull_policy is
  not allowed" (compose-only extension).
* ``restart-key`` -> ``compose_restart`` lookup. Silently ignored in
  swarm (operator's ``docker_restart_policy`` is dropped, swarm uses
  whatever ``deploy.restart_policy.condition`` is set to).

Suppress per offending line with ``# nocheck: <rule-name>`` either on
the same line or the line above.

Adding a new rule: append a ``ModeRule`` to ``_RULES``. The scaffolding
(file walk, suppression, line-grouping) is shared.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT


@dataclass(frozen=True)
class ModeRule:
    name: str
    description: str
    raw_regex: re.Pattern[str]
    remediation: str
    extra_regexes: tuple[re.Pattern[str], ...] = field(default_factory=tuple)


# Shared regexes for the `compose_only` lookup's broken call shapes. The
# lookup name is matched with both quote styles; the literal key term
# (`'container_name'` or `'pull_policy'` etc.) is the second positional
# argument right after the lookup name.
_CO_LOOKUP_NAME = r"""['"]compose_only['"]"""
# Split-Jinja form: `{{ lookup('compose_only', 'key', A }}-{{ B) }}` ->
# the outer `{{ }}` closes mid-call, Jinja raises a parse error.
_CO_BROKEN_SPLIT = re.compile(
    rf"lookup\(\s*{_CO_LOOKUP_NAME}\s*,[^)]*\}}\}}[^{{]*\{{\{{",
)
# Embedded-Jinja-in-literal-string form: `lookup('compose_only', 'key',
# "{{ X }}_suffix")` — deprecated in ansible-core 2.23. Use tilde
# concatenation: `X ~ '_suffix'`.
_CO_BROKEN_EMBED = re.compile(
    rf"lookup\(\s*{_CO_LOOKUP_NAME}\s*,\s*['\"][^'\"]*['\"]\s*,\s*['\"][^'\"]*\{{\{{",
)

# container-name regex --------------------------------------------------
_CN_RAW = re.compile(r"(?m)^\s*container_name\s*:")

# pull-policy regex -----------------------------------------------------
_PP_RAW = re.compile(r"(?m)^\s*pull_policy\s*:")

# restart-key regex -----------------------------------------------------
_RESTART_RAW = re.compile(r"(?m)^\s*restart\s*:")


_RULES: tuple[ModeRule, ...] = (
    ModeRule(
        name="container-name",
        description=(
            "Raw `container_name:` collides with swarm-mode replicas > 1 "
            "and aborts `docker stack deploy`."
        ),
        raw_regex=_CN_RAW,
        extra_regexes=(_CO_BROKEN_SPLIT, _CO_BROKEN_EMBED),
        remediation=(
            "Route through the generic `compose_only` lookup "
            "(plugins/lookup/compose_only.py) so the key is emitted in "
            "compose mode and omitted in swarm: "
            "`{{ lookup('compose_only', 'container_name', MY_CONTAINER) }}`."
        ),
    ),
    ModeRule(
        name="pull-policy-key",
        description=(
            "Raw `pull_policy:` is a compose-only extension; "
            "`docker stack deploy` rejects it with "
            "'Additional property pull_policy is not allowed'."
        ),
        raw_regex=_PP_RAW,
        remediation=(
            "Route through the generic `compose_only` lookup "
            "(plugins/lookup/compose_only.py) so the key is emitted in "
            "compose mode and omitted in swarm: "
            "`{{ lookup('compose_only', 'pull_policy', 'never') }}`."
        ),
    ),
    ModeRule(
        name="restart-key",
        description=(
            "Top-level `restart:` is silently ignored by swarm (replaced "
            "by `deploy.restart_policy`), producing warnings and "
            "double-declared intent."
        ),
        raw_regex=_RESTART_RAW,
        remediation=(
            "Route through the `compose_restart` lookup "
            "(plugins/lookup/compose_restart.py). With no argument it "
            "defers to `DOCKER_RESTART_POLICY`: "
            "`{{ lookup('compose_restart') }}`. Pass an explicit policy "
            "if a service needs an override: "
            "`{{ lookup('compose_restart', 'on-failure') }}`."
        ),
    ),
)


def _candidate_paths() -> list[Path]:
    out: list[Path] = []
    for s in iter_project_files():
        p = Path(s)
        if p.suffix.lower() != ".j2":
            continue
        try:
            rel = p.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) >= 3 and parts[0] == "roles" and "templates" in parts:
            out.append(p)
    return out


def _hits_for(text: str, rule: ModeRule) -> set[int]:
    hits: set[int] = set()
    for regex in (rule.raw_regex, *rule.extra_regexes):
        for m in regex.finditer(text):
            hits.add(text[: m.start()].count("\n") + 1)
    return hits


# Fast pre-filter substrings per rule: skip the regex if the literal key
# does not appear in the file at all. Cheap text-membership check.
_PREFILTER: dict[str, tuple[str, ...]] = {
    "container-name": ("container_name",),
    "pull-policy-key": ("pull_policy",),
    "restart-key": ("restart:",),
}


class TestModeIncompatibleKeys(unittest.TestCase):
    def test_no_mode_incompatible_keys_in_templates(self) -> None:
        offenders_by_rule: dict[str, list[str]] = {r.name: [] for r in _RULES}

        for path in _candidate_paths():
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            lines = text.splitlines()
            rel = path.relative_to(PROJECT_ROOT)

            for rule in _RULES:
                needles = _PREFILTER.get(rule.name, ())
                if needles and not any(n in text for n in needles):
                    continue
                hits = _hits_for(text, rule)
                for idx in sorted(hits):
                    if is_suppressed_at(lines, idx, rule.name):
                        continue
                    line_snip = lines[idx - 1].strip() if 1 <= idx <= len(lines) else ""
                    offenders_by_rule[rule.name].append(f"{rel}:{idx}: {line_snip}")

        sections: list[str] = []
        for rule in _RULES:
            items = offenders_by_rule[rule.name]
            if not items:
                continue
            sections.append(
                f"[{rule.name}] {rule.description}\n"
                f"  Fix: {rule.remediation}\n"
                f"  Suppress per line with `# nocheck: {rule.name}` if "
                "the literal key is genuinely required.\n"
                "  Offenders:\n    - " + "\n    - ".join(items)
            )

        if sections:
            self.fail(
                "Mode-incompatible YAML keys found in templates:\n\n"
                + "\n\n".join(sections)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

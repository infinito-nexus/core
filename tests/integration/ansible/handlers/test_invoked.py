"""The notify/listen contract of every handler.

A handler topic is an *identifier*, not a label: Ansible binds a `notify:` to a
handler by matching this string, so a typo does not misspell anything, it
silently changes which code runs (or aborts the play at the notify). Three
rules hold it together:

1. **Every `notify:` has a listener.** The target must be a `listen:` topic of
   some handler. Handler *names* are deliberately NOT accepted: a name is
   display text that the name lint is free to rewrite, a `listen:` topic is the
   contract. `package_notify:` counts as a notify wherever it appears.
2. **Every `listen:` is notified.** A topic nobody notifies is a handler that
   never runs -- dead code that reads as coverage.
3. **Both spell out as `[a-z_-]+`.** No spaces, no capitals, nothing else, so
   the identifier survives quoting, YAML flow style and a shell round-trip
   unchanged.

A `notify:` written as a Jinja expression is checked through its quoted string
literals (`{{ 'reload-system-daemon' if x else 'refresh-systemctl-service' }}`
contributes both). A notify that *interpolates* into a fixed shape
(`import-{{ folder }}-ldif-files`) becomes a pattern: it must match at least
one listener, and it satisfies every listener it matches -- the loop that
drives it is the reason those handlers are reachable at all. An expression that
carries no literal and no fixed text resolves only at runtime and is skipped:
it is reported by neither rule, in either direction.

Every project YAML is scanned rather than only `roles/*/handlers/main.yml` plus
`roles/*/tasks/**`. That is what makes an `import_tasks` split (`compose.yml` /
`swarm.yml`) and a notify carried through a data structure
(`vars.role_templates[].notify`, handed to a generic renderer later) visible
without teaching this file how either mechanism works.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from utils.cache.files import iter_project_files

from . import PROJECT_ROOT

IDENTIFIER = re.compile(r"^[a-z_-]+$")

NOTIFY_KEYS = ("notify", "package_notify")

_JINJA = re.compile(r"{{.*?}}", re.DOTALL)
_LITERAL = re.compile(r"'([^']*)'|\"([^\"]*)\"")
_INTERPOLATION = "[a-z0-9_-]+"

_yaml = YAML(typ="safe")
_yaml.allow_duplicate_keys = True


def _load(path: str):
    """The parsed YAML, or ``None`` when it does not parse.

    Files whose Jinja or tags defeat a safe parse are policed by the yaml lint
    elsewhere; skipping them here keeps this check off unrelated noise.
    """
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return _yaml.load(handle)
    except Exception:
        return None


def _walk(node):
    """Every mapping in the document, whatever nests it."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)


def _entries(value) -> list[str]:
    """The non-empty strings a value holds. ``package_notify: ""`` is the
    documented way to notify nothing, so an empty entry names no topic."""
    return [
        entry.strip()
        for entry in (value if isinstance(value, list) else [value])
        if isinstance(entry, str) and entry.strip()
    ]


def topics(value) -> list[str]:
    """The topic strings one ``notify:``/``listen:`` value names outright.

    A pure Jinja expression contributes its quoted literals, which is what
    makes a conditional notify checkable; an expression built only from
    variables contributes nothing and is therefore neither demanded nor blamed.
    """
    found: list[str] = []
    for entry in _entries(value):
        if not _JINJA.search(entry):
            found.append(entry)
            continue
        found += [
            literal
            for match in _LITERAL.finditer(entry)
            for literal in match.groups()
            if literal
        ]
    return found


def patterns(value) -> list[tuple[str, re.Pattern[str]]]:
    """The topic shapes one ``notify:`` interpolates into.

    ``import-{{ folder }}-ldif-files`` is neither a topic nor unknowable: the
    fixed text around the interpolation is the contract, and the loop variable
    only chooses between the listeners that fit it.
    """
    shapes = []
    for entry in _entries(value):
        if not _JINJA.search(entry) or _LITERAL.search(entry):
            continue
        fixed = [re.escape(part) for part in _JINJA.split(entry)]
        if not any(part for part in fixed):
            continue
        shapes.append((entry, re.compile("^" + _INTERPOLATION.join(fixed) + "$")))
    return shapes


def collect():
    """Every notified topic, every declared listener and every notify shape,
    each mapped to the files it appears in."""
    notified: dict[str, list[str]] = {}
    listened: dict[str, list[str]] = {}
    shapes: dict[str, tuple[re.Pattern[str], list[str]]] = {}
    for path_str in iter_project_files(extensions=(".yml", ".yaml")):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        data = _load(path_str)
        if data is None:
            continue
        for node in _walk(data):
            for key in ("listen", *NOTIFY_KEYS):
                if key not in node:
                    continue
                bucket = listened if key == "listen" else notified
                for topic in topics(node[key]):
                    bucket.setdefault(topic, []).append(rel)
                if key != "listen":
                    for raw, shape in patterns(node[key]):
                        shapes.setdefault(raw, (shape, []))[1].append(rel)
    return notified, listened, shapes


class TestHandlersInvoked(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.notified, cls.listened, cls.shapes = collect()

    def test_every_notify_has_a_listener(self) -> None:
        orphans = {
            topic: sorted(set(files))
            for topic, files in self.notified.items()
            if topic not in self.listened
        }
        orphans.update(
            {
                raw: sorted(set(files))
                for raw, (shape, files) in self.shapes.items()
                if not any(shape.match(topic) for topic in self.listened)
            }
        )
        self.assertEqual(
            orphans,
            {},
            "notify target(s) that no handler listens for. The play either "
            "aborts at the notify or silently does nothing. Add "
            "'listen: <topic>' to the handler that should run, or drop the "
            "notify:\n"
            + "\n".join(f"  {t}: {', '.join(f)}" for t, f in sorted(orphans.items())),
        )

    def test_every_listener_is_notified(self) -> None:
        unreachable = {
            topic: sorted(set(files))
            for topic, files in self.listened.items()
            if topic not in self.notified
            and not any(shape.match(topic) for shape, _ in self.shapes.values())
        }
        self.assertEqual(
            unreachable,
            {},
            "listen topic(s) nobody notifies. Those handlers never run, which "
            "reads as coverage the deploy does not have. Notify them from the "
            "task that should trigger them, or delete the handler:\n"
            + "\n".join(
                f"  {t}: {', '.join(f)}" for t, f in sorted(unreachable.items())
            ),
        )

    def test_topics_are_lowercase_identifiers(self) -> None:
        offenders = sorted(
            {
                f"{topic!r} ({key}): {', '.join(sorted(set(files)))}"
                for key, bucket in (
                    ("notify", self.notified),
                    ("listen", self.listened),
                )
                for topic, files in bucket.items()
                if not IDENTIFIER.match(topic)
            }
            | {
                f"{raw!r} (notify): {', '.join(sorted(set(files)))}"
                for raw, (_shape, files) in self.shapes.items()
                if not IDENTIFIER.match(_JINJA.sub("x", raw))
            }
        )
        self.assertEqual(
            offenders,
            [],
            f"handler topic(s) outside {IDENTIFIER.pattern}. A topic is an "
            "identifier, not a sentence: lowercase, with '-' or '_' where a "
            "space would go:\n" + "\n".join(f"  {o}" for o in offenders),
        )


if __name__ == "__main__":
    unittest.main()

"""A healthcheck must find every program it runs in the image it runs in.

A stripped base carries the runtime and little else, and which "little else"
differs per family. The declaration does not know that: ``flavor: curl`` renders
``CMD curl -f <url>`` and ``flavor: tcp`` renders ``CMD bash -c`` over
``/dev/tcp`` whatever the image underneath is. Where the program is absent the
probe fails from its first beat and the container never reports healthy.

The two deploy modes answer differently, and neither answer names the program.
``sys-svc-compose`` waits on the database container alone in compose and on
every stack task in swarm, so a permanently unhealthy service passes unnoticed
under compose and stops the deploy under swarm: the task dies with ``non-zero
exit (137): dockerexec: unhealthy container``, is rescheduled, dies again, and
the wait fails. Every deployment holding the service in its closure fails with
it, reported against the service that was waited for.

What is checked
===============
Every ``meta/services.yml`` healthcheck whose service sits on a base this file
has measured. The programs come from the probe the declaration renders
(:func:`utils.docker.healthcheck.compose.compose`), both its ``CMD`` and its
``CMD-SHELL`` form, so a flavor that changes its command moves this check with
it rather than drifting from a table restated here. ``||`` in a shell probe is
read as alternatives, ``&&`` and ``;`` as a sequence that needs all of its
parts, and shell builtins are dropped so a trailing ``|| exit 1`` cannot make
every requirement look satisfiable.

A requirement is met when the measured base provides the program or the role's
``files/Dockerfile`` installs it. A base that is neither family is skipped: a
vendor image's contents are not knowable from the tree, and for most of them
there is no Dockerfile of ours to add anything to.

Per-service opt-out
===================
``# nocheck: healthcheck-binary`` on the ``flavor`` line or the one above it,
with a reason naming where the program comes from instead.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.docker.healthcheck.compose import compose
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

RULE = "healthcheck-binary"

PROVIDED: dict[str, frozenset[str]] = {
    "slim": frozenset({"bash", "sh"}),
    "alpine": frozenset({"sh", "wget", "nc"}),
}
"""What each stripped family ships, read out of the images themselves.

Measured with ``docker create`` plus ``docker cp``, which reports a path that is
absent instead of reporting a shell's opinion of it. Every lookup covered
``/usr/bin``, ``/bin``, ``/usr/local/bin`` and ``/sbin``:

* ``debian:13-slim``, ``node:26-slim`` and ``python:3.13.15-slim`` carry
  ``/bin/bash`` at 1298416 bytes and none of ``curl``, ``wget`` or ``nc``. bash
  is Essential in Debian and the other three are not, which is the whole
  difference between the stripped tag and the full one: the full ``node:26``
  variant carries ``/usr/bin/curl`` at 280800 bytes.
* ``redis:8-alpine`` and ``node:26-alpine`` carry ``/usr/bin/wget`` and
  ``/usr/bin/nc`` as busybox applets, no ``curl``, and no ``/bin/bash`` at all.
  Their ``/bin/sh`` is busybox, which does not implement ``/dev/tcp``, so the
  flavors built on that redirection need the real shell rather than any shell.

The family is read from the tag, which holds for every image in the tree today:
every ``slim`` tag here is Debian based and every ``alpine`` tag is Alpine
based. Adding a family means measuring it the same way, not inferring it.
"""

IMAGE_PROVIDES: dict[str, frozenset[str]] = {
    "nginx": frozenset({"curl"}),
}
"""Programs an individual image adds on top of what its family ships.

nginx installs curl in both of its variants: ``/usr/bin/curl`` at 272432 bytes
in ``nginx:1.31.6-alpine`` and at 321880 bytes in the Debian ``nginx:1.31``.
Base Alpine does not have it at all, measured the same way on ``redis:8-alpine``
and ``node:26-alpine``. Reading nginx's curl as a property of Alpine would pass
a ``curl`` flavor on any alpine image, so it is recorded against the image that
installs it.
"""

SHELL_BUILTINS = frozenset({"exit", "true", "false", "test", "[", ":", "echo"})
"""Words a probe may invoke that no package provides."""


def _families(version: object) -> list[str]:
    """The measured families a version tag names, in declaration order."""
    text = str(version)
    return [family for family in PROVIDED if family in text]


def _image_extras(image: object) -> frozenset[str]:
    """What this particular image adds beyond its family.

    Args:
        image: the ``image`` value, with or without a registry prefix.
    """
    name = str(image).rsplit("/", 1)[-1]
    return IMAGE_PROVIDES.get(name, frozenset())


def _requirements(flavor: object) -> list[list[str]]:
    """The programs a declared flavor runs, as alternatives of sequences.

    ``[["wget"], ["curl"]]`` means either one satisfies the probe;
    ``[["msmtp", "curl"]]`` would mean it needs both.

    Args:
        flavor: the ``healthcheck.flavor`` value, one name or a list.
    """
    try:
        test = [
            str(part)
            for part in compose(flavor, port=80, path="/", hostname="h").test()
        ]
    except Exception:
        return []
    if not test:
        return []
    if test[0] == "CMD":
        return [[test[1]]] if len(test) > 1 else []
    if len(test) < 2:
        return []
    groups: list[list[str]] = []
    for alternative in re.split(r"\|\|", test[1]):
        words = [
            segment.strip().split()[0]
            for segment in re.split(r"&&|;", alternative)
            if segment.strip()
        ]
        needed = [word for word in words if word not in SHELL_BUILTINS]
        if needed:
            groups.append(needed)
    return groups


def _installs(dockerfile_body: str, program: str) -> bool:
    """Whether the Dockerfile names the program as something it installs."""
    pattern = rf"(?<![\w-]){re.escape(program)}(?![\w-])"
    return re.search(pattern, dockerfile_body) is not None


def _flavor_lines(lines: list[str]) -> dict[str, int]:
    """The 1-based ``flavor:`` line of each top-level service key.

    ``meta/services.yml`` maps one service per top-level key, so the flavor a
    key owns is the first one under it. Taking the file's first flavor line
    instead would let one service's marker silence another's.

    Args:
        lines: the file's lines, as :func:`read_text` splits them.
    """
    found: dict[str, int] = {}
    current: str | None = None
    for number, line in enumerate(lines, start=1):
        key = re.match(r"([A-Za-z0-9_.-]+):\s*(?:#.*)?$", line)
        if key:
            current = key.group(1)
            continue
        if current and current not in found and re.match(r"\s+flavor:", line):
            found[current] = number
    return found


class TestHealthcheckBinaryOnSlimBase(unittest.TestCase):
    def test_a_stripped_base_provides_every_program_its_healthcheck_runs(self):
        offenders = []
        for services in sorted(
            (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
        ):
            role_dir = services.parent.parent
            data = load_yaml_any(str(services), default_if_missing={}) or {}
            lines = read_text(str(services)).splitlines()
            flavor_lines = _flavor_lines(lines)
            for key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                health = entry.get("healthcheck")
                if not isinstance(health, dict) or "flavor" not in health:
                    continue
                families = _families(entry.get("version", ""))
                if not families:
                    continue
                groups = _requirements(health["flavor"])
                if not groups:
                    continue
                if is_suppressed_at(lines, flavor_lines.get(key, 0), RULE):
                    continue
                dockerfile = role_dir / "files" / "Dockerfile"
                body = read_text(str(dockerfile)) if dockerfile.is_file() else ""
                available = set().union(*(PROVIDED[family] for family in families))
                available |= _image_extras(entry.get("image", ""))
                satisfied = any(
                    all(
                        program in available or _installs(body, program)
                        for program in group
                    )
                    for group in groups
                )
                if satisfied:
                    continue
                wanted = " or ".join(" and ".join(group) for group in groups)
                offenders.append(
                    f"{role_dir.name}: service '{key}' declares healthcheck "
                    f"flavor {health['flavor']!r}, which runs {wanted}, on the "
                    f"{'/'.join(families)} image {entry.get('image')}:"
                    f"{entry.get('version')} that provides "
                    f"{', '.join(sorted(available))}; "
                    + (
                        "files/Dockerfile installs none of them"
                        if body
                        else "the role has no files/Dockerfile"
                    )
                )

        self.assertEqual(
            [],
            offenders,
            "A stripped base carries the runtime and little else, so a program a "
            "healthcheck runs has to come from the base or from the role that "
            "depends on it. Install it in the role's files/Dockerfile, pick a "
            "flavor the image can already run, or mark the line "
            f"`# nocheck: {RULE}` with a reason naming where the program comes "
            "from:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()

"""Resolve the explicit role subset declared in a pull-request body.

Activated by the ``🧩 Subset`` label: the entry-pull-request workflow only
runs this module when the label is present. It gives fork contributors the
selective-CI capability that ``entry-manual.yml`` (``workflow_dispatch``)
grants maintainers, which forks cannot trigger.

It reads the PR body from ``$PR_BODY``, extracts the first fenced code block
whose YAML defines a ``roles:`` list, validates that every listed id is an
existing ``roles/<id>`` directory, and writes ``whitelist`` (space-separated)
and ``roles_only=true`` to ``$GITHUB_OUTPUT`` -- the same outputs the
diff-derived resolver produces.

Unlike the fail-safe diff resolver (which widens to ``__ALL__`` on any
problem), the subset path is strict: invalid YAML, a missing/empty ``roles:``
list, or an unknown role id each abort with a clear message and a non-zero
exit, so a mistyped subset never silently deploys the wrong set. Role ids must
match ``^[a-z0-9-]+$``, which also blocks path traversal before any filesystem
lookup.

Invoked from scripts/github/resolve/pr_affected_roles.sh via
``python -m cli.meta.ci.subset_roles``.
"""

import os
import re
import sys
from pathlib import Path
from typing import NoReturn

import yaml

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_str

ROLES_DIR = PROJECT_ROOT / "roles"
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
NAME_RE = re.compile(r"^[a-z0-9-]+$")


def fail(message: str) -> NoReturn:
    print(f"Subset roles error: {message}", file=sys.stderr)
    sys.exit(1)


def extract_roles(body: str):
    blocks = FENCE_RE.findall(body)
    if not blocks:
        fail(
            "the '🧩 Subset' label is set but the PR body has no fenced "
            "```yaml block. Add a '## Roles' section with a `roles:` list."
        )
    for block in blocks:
        try:
            data = load_yaml_str(block)
        except yaml.YAMLError as exc:
            fail(f"invalid YAML in the PR body roles block: {exc}")
        if isinstance(data, dict) and "roles" in data:
            return data["roles"]
    fail(
        "no `roles:` key found in any YAML block of the PR body. Declare the "
        "subset as a `roles:` list under a '## Roles' section."
    )


def main() -> None:
    roles = extract_roles(os.environ.get("PR_BODY", ""))
    if roles is None:
        roles = []
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        fail("`roles:` must be a YAML list of role-id strings.")

    roles = [r.strip() for r in roles if r and r.strip()]
    if not roles:
        fail(
            "the '🧩 Subset' label is set but the `roles:` list is empty. "
            "List at least one role id or remove the label."
        )

    invalid = sorted({r for r in roles if not NAME_RE.fullmatch(r)})
    if invalid:
        fail(
            "invalid role id(s) (allowed: lowercase letters, digits, '-'): "
            + ", ".join(invalid)
        )

    unknown = sorted({r for r in roles if not (ROLES_DIR / r).is_dir()})
    if unknown:
        fail("unknown role id(s): " + ", ".join(unknown))

    whitelist = " ".join(roles)
    print(f"Subset roles resolved from PR body: {whitelist}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"whitelist={whitelist}\n")
            handle.write("roles_only=true\n")


if __name__ == "__main__":
    main()

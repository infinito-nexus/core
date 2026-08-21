"""Run the .env generator with every non-stdlib, non-repo import blocked.

Executed as a subprocess, never imported. Argv is ``<repo-root> <out-path>``.
A blocked import propagates so the traceback names the offending chain.

``sys.modules`` is consulted before ``sys.meta_path``, and ``site`` preloads
whatever the interpreter's ``.pth`` files pull in (setuptools' ``_distutils_hack``,
an editable-install finder). Those entries are dropped first, otherwise a
third-party import would resolve straight out of the cache, unblocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
sys.path.insert(0, str(REPO))

REPO_TOP = frozenset(
    {"cli", "utils", "plugins", "filter_plugins", "lookup_plugins", "module_utils"}
)
STDLIB = frozenset(sys.stdlib_module_names)


class Blocker:
    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        if top in STDLIB or top in REPO_TOP:
            return
        raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)


for _name in list(sys.modules):
    _top = _name.split(".")[0]
    if _top not in STDLIB and _top not in REPO_TOP and _name != "__main__":
        del sys.modules[_name]

sys.meta_path.insert(0, Blocker())

from cli.meta.env.__main__ import (  # noqa: E402
    build_env,
    parse_static_env_with_comments,
    write_dotenv,
)

static, comments = parse_static_env_with_comments(REPO / "default.env")
eb = build_env(static, repo_root=REPO, comments=comments)
write_dotenv(eb, OUT)
print(len(eb.values))

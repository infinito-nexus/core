from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "scripts" / "meta" / "resolve" / "missing" / "highest_release_tag.sh"
)
TAGS = ("v9.0.0", "v9.0.1", "v9.0.2", "v14.1.0", "v15.0.0")
STUBS = {
    "git": '#!/usr/bin/env bash\nprintf "%s\\n" ${STUB_TAGS}\n',
    "docker": (
        "#!/usr/bin/env bash\n"
        'case " ${STUB_MISSING} " in *" ${3##*:} "*) exit 1 ;; esac\n'
    ),
}


def pick(*missing: str) -> subprocess.CompletedProcess:
    """Run the picker against stubbed ``git`` tags and ``docker`` manifests.

    Args:
        missing: tags whose images the registry does not hold.
    """
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in STUBS.items():
            stub = Path(tmp) / name
            stub.write_text(body)
            stub.chmod(0o755)
        env = {
            **{k: v for k, v in os.environ.items() if k != "BASH_ENV"},
            "PATH": f"{tmp}{os.pathsep}{os.environ['PATH']}",
            "STUB_TAGS": " ".join(TAGS),
            "STUB_MISSING": " ".join(missing),
            "OWNER": "acme",
            "REGISTRY": "ghcr.io",
            "REPO_PREFIX": "core",
            "INFINITO_DISTROS": "debian arch",
        }
        return subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )


class TestHighestReleaseTag(unittest.TestCase):
    def test_tags_below_the_oldest_buildable_one_are_not_picked(self) -> None:
        self.assertEqual("", pick("v9.0.1", "v9.0.0").stdout)

    def test_the_oldest_buildable_tag_is_picked(self) -> None:
        self.assertEqual("v9.0.2\n", pick("v9.0.2", "v9.0.1").stdout)

    def test_the_highest_missing_tag_is_picked(self) -> None:
        self.assertEqual("v14.1.0\n", pick("v14.1.0", "v9.0.1").stdout)


if __name__ == "__main__":
    unittest.main()

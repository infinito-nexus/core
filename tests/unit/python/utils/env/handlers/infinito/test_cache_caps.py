from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import PROJECT_ROOT
from utils.env.builder import build_env
from utils.env.parser import parse_static_env_with_comments

FIXED = {
    "INFINITO_CACHE_REGISTRY_MAX_SIZE": "40g",
    "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX": "20g",
    "INFINITO_CACHE_SHARED_MAX_SIZE": "10g",
    "INFINITO_TOOLS_MODELS_MAX_SIZE": "30g",
    "INFINITO_BUILD_CACHE_MAX_SIZE": "20g",
    "INFINITO_CACHE_MAX_IDLE_DAYS": "30",
    "INFINITO_CACHE_DISK_FLOOR": "15g",
}

DF_STUB = "#!/usr/bin/env bash\nprintf 'Avail\\n%s\\n' \"${STUB_AVAIL_GB}\"\n"


def _written(
    free_gb: int, exported: dict[str, str], custom: str
) -> dict[str, str | None]:
    """Args:
        free_gb: the free space every `df` call reports, in GB.
        exported: cache variables the caller's environment sets.
        custom: the content of the checkout's custom.env, empty for none.

    Returns:
        The value the builder writes for every fixed cache variable, None when it writes none.
    """
    static, comments = parse_static_env_with_comments(PROJECT_ROOT / "default.env")
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "df"
        stub.write_text(DF_STUB)
        stub.chmod(0o755)
        checkout = Path(tmp) / "checkout"
        checkout.mkdir()
        if custom:
            (checkout / "custom.env").write_text(custom)
        environ = dict.fromkeys(FIXED, "")
        environ.update(exported)
        environ["STUB_AVAIL_GB"] = str(free_gb)
        environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
        with patch.dict(os.environ, environ, clear=False):
            eb = build_env(static, checkout, comments=comments)
    return {key: eb.values.get(key) for key in FIXED}


class TestFixedCacheCaps(unittest.TestCase):
    def test_dotenv_writes_the_fixed_caps_the_idle_window_and_the_floor(self) -> None:
        self.assertEqual(_written(54, {}, ""), FIXED)

    def test_no_written_value_depends_on_the_free_disk(self) -> None:
        self.assertEqual(_written(8, {}, ""), _written(8000, {}, ""))

    def test_an_exported_value_wins(self) -> None:
        written = _written(
            54,
            {
                "INFINITO_CACHE_SHARED_MAX_SIZE": "5g",
                "INFINITO_CACHE_MAX_IDLE_DAYS": "7",
            },
            "",
        )
        self.assertEqual(
            written,
            {
                **FIXED,
                "INFINITO_CACHE_SHARED_MAX_SIZE": "5g",
                "INFINITO_CACHE_MAX_IDLE_DAYS": "7",
            },
        )

    def test_a_custom_env_value_wins(self) -> None:
        written = _written(
            54,
            {},
            "INFINITO_BUILD_CACHE_MAX_SIZE=7g\nINFINITO_CACHE_DISK_FLOOR=25g\n",
        )
        self.assertEqual(
            written,
            {
                **FIXED,
                "INFINITO_BUILD_CACHE_MAX_SIZE": "7g",
                "INFINITO_CACHE_DISK_FLOOR": "25g",
            },
        )


if __name__ == "__main__":
    unittest.main()

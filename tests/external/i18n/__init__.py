"""Translation checks that need the live engine the tools lane deploys.

They are external because the behaviour under test is the engine's own output
and no hermetic stand-in reproduces it: a fake returns whatever it was told
to. The live dependency is this repository's own LibreTranslate, brought up
by the tools lane rather than reached over the internet.

Checks whose verdict comes from System One live in ``tests/oracle``; the ones
decidable from the catalogs alone live in ``tests/integration/i18n``.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SUITE = "external-i18n"

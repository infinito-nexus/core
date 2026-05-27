#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

# This file is invoked directly as a script (the ``cli`` console-script
# entry-point and the integration help-test), in which case
# ``from . import PROJECT_ROOT`` fails with ``attempted relative import
# with no known parent package``. Compute the repo root
# locally and prepend it to sys.path before any project-package import
# resolves. Without this, sys.path[0] points to ``<root>/cli`` and
# importing ``cli.*`` may accidentally resolve to an installed package
# from site-packages.
# nocheck: project-root-import  sys.path bootstrap before package imports resolve
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.env.loader import load_dotenv_once  # noqa: E402

load_dotenv_once(PROJECT_ROOT)

from cli.core.app import main  # noqa: E402

if __name__ == "__main__":
    main()

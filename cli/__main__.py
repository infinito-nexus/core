#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

# nocheck: project-root-import  sys.path bootstrap before package imports resolve
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.env.loader import load_dotenv_once  # noqa: E402

load_dotenv_once(PROJECT_ROOT)

from cli.core.app import main  # noqa: E402

if __name__ == "__main__":
    main()

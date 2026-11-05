"""Load the elector package under ``infinito_elector_src``.

This test package mirrors the source path, so it shares the name
``infinito_elector``; under pytest's importlib mode a plain import would
resolve to this package instead of the code under test.
"""

import importlib.util
import sys

from utils import PROJECT_ROOT

_SRC = PROJECT_ROOT / "files" / "db-elector" / "infinito_elector"
_NAME = "infinito_elector_src"

if _NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _NAME, _SRC / "__init__.py", submodule_search_locations=[str(_SRC)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_NAME] = _module
    _spec.loader.exec_module(_module)

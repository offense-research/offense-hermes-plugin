"""Load the plugin as a package so tests exercise the real relative imports.

Hermes imports a plugin directory as a package. Loading it here the same way
means the tests fail if a relative import is wrong, instead of discovering it
at install time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "offense_plugin"

if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

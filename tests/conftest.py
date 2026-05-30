"""Pytest bootstrap — ensure the repo root is on sys.path so ``import app``
resolves without installing the package.
"""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

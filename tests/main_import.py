"""
tests/main_import.py — import ``main`` without touching the user's files.

``main`` configures logging (``app.log``), ``faulthandler`` (``crash.log``) and its data
paths from ``%APPDATA%`` at import time; importing it straight from a test wrote test
runs into the real logs. Point APPDATA at a temp folder for that first import.
"""

import os
import sys
import tempfile
from unittest import mock


def import_main():
    if "main" in sys.modules:
        return sys.modules["main"]
    with mock.patch.dict(os.environ, {"APPDATA": tempfile.mkdtemp(prefix="overlay-test-")}):
        import main
    return main

"""Puts tools/ on the import path and names the client data the tests read, skipped where it is absent."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spiraltools.lang import ROOTWAD_DIR  # noqa: E402
from spiraltools.wad import GAMEDATA_DIR  # noqa: E402

needs_rootwad = unittest.skipUnless(os.path.isdir(ROOTWAD_DIR), f"no root wad at {ROOTWAD_DIR}")
needs_gamedata = unittest.skipUnless(os.path.isdir(GAMEDATA_DIR), f"no client GameData at {GAMEDATA_DIR}")

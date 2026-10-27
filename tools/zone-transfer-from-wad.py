#!/usr/bin/env python3
"""Rebuild ZoneTransfer entries for a zone from the client's zone wad.

The `zones` command of tools/spiraltools.py under its old name; see tools/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spiraltools import zones

if __name__ == "__main__":
    zones.main()

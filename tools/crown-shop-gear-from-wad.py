#!/usr/bin/env python3
"""List the crowns-only gear of the client's root wad in the crown shop's Gear tab.

The `crownshop` command of tools/spiraltools.py under its old name; see tools/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spiraltools import crownshop

if __name__ == "__main__":
    crownshop.main()

#!/usr/bin/env python3
"""Build questgen specs for a world from the Internet Archive's copies of the Wizard101 Central wiki.

The `archive` command of tools/spiraltools.py under its old name; see tools/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spiraltools.quests import archive

if __name__ == "__main__":
    archive.main()

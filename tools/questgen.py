#!/usr/bin/env python3
"""Generate quest templates and their drop tables from one JSON spec per quest.

The `quests` command of tools/spiraltools.py under its old name; see tools/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spiraltools.quests import generate

if __name__ == "__main__":
    generate.main()

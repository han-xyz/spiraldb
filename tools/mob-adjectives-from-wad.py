#!/usr/bin/env python3
"""List the mobs of a world's object templates: display name, template, template id and adjectives.

The `mobs` command of tools/spiraltools.py under its old name; see tools/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spiraltools import templates

if __name__ == "__main__":
    templates.mobs_main()

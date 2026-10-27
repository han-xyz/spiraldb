#!/usr/bin/env python3
"""List the quest NPCs of a world: persona, display name, template id, portrait and the zones that place them.

The `npcs` command of tools/spiraltools.py under its old name; see tools/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spiraltools import templates

if __name__ == "__main__":
    templates.npcs_main()

#!/usr/bin/env python3
"""The spiraldb tools in one command: python3 -I tools/spiraltools.py <command> --help. See tools/README.md."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spiraltools import cli

if __name__ == "__main__":
    sys.exit(cli.main())

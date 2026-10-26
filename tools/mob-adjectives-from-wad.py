#!/usr/bin/env python3
"""List the mobs of a world's object templates: display name, template, template id and adjectives.

See tools/README.md for usage and how a quest's bounty goal uses the adjectives.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client_data import (ADJECTIVE_LIST, DISPLAY_NAME, ROOTWAD_DIR, read_binary_xml, read_lang, string_field,
                         string_list_field, template_ids)

MOB_LANG = "WizardMobs"


def mobs(rootwad, folder):
    names = read_lang(rootwad, MOB_LANG)
    ids = template_ids(rootwad)
    directory = os.path.join(rootwad, "ObjectData", folder)
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".xml"):
            continue
        data = read_binary_xml(os.path.join(directory, filename))
        display = string_field(data, DISPLAY_NAME) or ""
        lang_name, _, key = display.rpartition("_")
        if lang_name != MOB_LANG:
            continue
        template = filename[:-4]
        yield (names.get(key, display), template, ids.get(f"ObjectData/{folder}/{filename}", 0),
               string_list_field(data, ADJECTIVE_LIST))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", nargs="*", default=["CL"], help="ObjectData folders, default CL")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    args = parser.parse_args()
    rows = sorted(row for folder in args.folders for row in mobs(args.rootwad, folder))
    print("display name\ttemplate\ttemplate id\tadjectives")
    for name, template, template_id, adjectives in rows:
        print(f"{name}\t{template}\t{template_id}\t{','.join(adjectives)}")


if __name__ == "__main__":
    main()

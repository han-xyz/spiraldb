#!/usr/bin/env python3
"""List the quest NPCs of a world: persona, display name, template id, portrait and the zones that place them.

See tools/README.md for usage and how a quest spec names its personas.
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client_data import (DISPLAY_NAME, GAMEDATA_DIR, ROOTWAD_DIR, lang_exists, read_binary_xml, read_lang, read_wad,
                         string_field,
                         template_ids)

PERSONA_SUFFIX = b"_Persona"
PORTRAIT = re.compile(rb"GUI/NpcPortraits/[ -~]+?\.dds")


def persona_of(data):
    """The questing persona string, found by its suffix and checked against its length byte."""
    end = data.find(PERSONA_SUFFIX)
    if end < 0:
        return None
    end += len(PERSONA_SUFFIX)
    run_start = end - 1
    while run_start > 0 and 32 <= data[run_start - 1] < 127:
        run_start -= 1
    for start in range(run_start - 1, end):
        if data[start] == 2 * (end - start - 1):
            return data[start + 1:end].decode("latin1")
    return None


def display_name(rootwad, key, langs):
    lang_name, _, entry = key.rpartition("_")
    if lang_name not in langs:
        langs[lang_name] = read_lang(rootwad, lang_name) if lang_name and lang_exists(rootwad, lang_name) else {}
    return langs[lang_name].get(entry, key)


def zone_placements(gamedata, world, templates):
    """template name -> zones whose gamedata.bin names it."""
    placed = {name: [] for name in templates}
    for path in sorted(glob.glob(os.path.join(gamedata, f"{world}-*.wad"))):
        data = read_wad(path, {"gamedata.bin"}).get("gamedata.bin", b"")
        zone = os.path.basename(path)[:-4].replace("-", "/")
        for name in templates:
            if name.encode() in data:
                placed[name].append(zone)
    return placed


def npcs(rootwad, folder):
    ids = template_ids(rootwad)
    langs = {}
    directory = os.path.join(rootwad, "ObjectData", folder)
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".xml"):
            continue
        data = read_binary_xml(os.path.join(directory, filename))
        persona = persona_of(data)
        if persona is None:
            continue
        key = string_field(data, DISPLAY_NAME) or ""
        portrait = PORTRAIT.search(data)
        yield {
            "template": filename[:-4],
            "persona": persona,
            "name": display_name(rootwad, key, langs) if key else "",
            "name_key": key,
            "template_id": ids.get(f"ObjectData/{folder}/{filename}", 0),
            "portrait": portrait.group().decode() if portrait else "",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", default="CL", help="ObjectData folder of the world's templates, default CL")
    parser.add_argument("--world", default="Celestia", help="zone wad prefix of the world, default Celestia")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    parser.add_argument("--gamedata", default=GAMEDATA_DIR, help="the client's Data/GameData directory")
    args = parser.parse_args()
    rows = list(npcs(args.rootwad, args.folder))
    placed = zone_placements(args.gamedata, args.world, [row["template"] for row in rows])
    print("persona\tname\tname key\ttemplate\ttemplate id\tportrait\tzones")
    for row in sorted(rows, key=lambda r: r["persona"]):
        print("\t".join([row["persona"], row["name"], row["name_key"], row["template"], str(row["template_id"]),
                         row["portrait"], ",".join(placed[row["template"]])]))


if __name__ == "__main__":
    main()

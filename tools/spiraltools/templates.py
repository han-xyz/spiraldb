"""The root wad's object templates: the template manifest, mob adjectives and NPC personas."""
import argparse
import functools
import glob
import os
import re
import struct
import zlib

from .lang import ROOTWAD_DIR, lang_exists, read_lang
from .wad import GAMEDATA_DIR, read_wad, zone_of_wad
from .worlds import world

ZLIB_HEADER = b"\x78\x9c"
MANIFEST_ENTRY = re.compile(rb"(?s)\xbc\x90\xce\xb9(.)(ObjectData/[ -~]+?\.xml)\x60\x00\x00\x00\x3a\x8f\x35\x89(.{4})")
ADJECTIVE_LIST = b"\x06\x16\x73\xbe"
DISPLAY_NAME = b"\x92\xbc\xd8\x91"
MOB_LANG = "WizardMobs"
PERSONA_SUFFIX = b"_Persona"
PORTRAIT = re.compile(rb"GUI/NpcPortraits/[ -~]+?\.dds")
QUEST_ICON = re.compile(rb"GUI/QuestButtons/Quest_([ -~]+?)(?:_off)?\.dds")
INTERACTABLE = b"InteractableBehavior"
MOBS_DESCRIPTION = "List the mobs of a world's object templates: display name, template, template id and adjectives."
ITEMS_DESCRIPTION = ("List the items of a world's object templates, the objects a usage goal names: display name, "
                     "quest icon name, template, template id and adjectives.")
NPCS_DESCRIPTION = ("List the quest NPCs of a world: persona, display name, template id, portrait and the zones that "
                    "place them.")


def read_binary_xml(path):
    """A BINd file, its body zlib-compressed when the manifest-style header carries a stream."""
    with open(path, "rb") as f:
        data = f.read()
    start = data.find(ZLIB_HEADER, 8, 16)
    if start < 0:
        return data
    try:
        return zlib.decompress(data[start:])
    except zlib.error:
        return data


def _compact_string(data, i):
    length = data[i] // 2
    return data[i + 1:i + 1 + length].decode("latin1"), i + 1 + length


def string_field(data, field_hash):
    """The first string stored under a field of a BINd template, or None."""
    i = data.find(field_hash)
    return None if i < 0 else _compact_string(data, i + len(field_hash))[0]


def string_list_field(data, field_hash):
    """A list-of-strings field of a BINd template: a byte of twice the count, then the strings."""
    i = data.find(field_hash)
    if i < 0:
        return []
    i += len(field_hash)
    count = data[i] // 2
    i += 1
    found = []
    for _ in range(count):
        text, i = _compact_string(data, i)
        found.append(text)
    return found


def template_ids(rootwad):
    """ObjectData manifest path -> template id."""
    manifest = read_binary_xml(os.path.join(rootwad, "TemplateManifest.xml"))
    ids = {}
    for m in MANIFEST_ENTRY.finditer(manifest):
        if m.group(1)[0] == 2 * len(m.group(2)):
            ids[m.group(2).decode()] = struct.unpack("<I", m.group(3))[0]
    return ids


def mobs(rootwad, folder):
    """(display name, template, template id, adjectives) of the mobs of an ObjectData folder."""
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


def icon_name(data, folder):
    """The words of the object's quest button icon, without the folder prefix and numbering: `kraken statue`."""
    icon = QUEST_ICON.search(data)
    if not icon:
        return ""
    words = re.sub(rf"^{folder}_", "", icon.group(1).decode(), flags=re.I).replace("_", " ")
    return re.sub(r"[\s\d]+$", "", words).lower()


def items(rootwad, folder):
    """The object templates of an ObjectData folder that a usage goal can name: those with an adjective that the
    player can interact with or whose display name is not a mob's."""
    ids = template_ids(rootwad)
    langs = {}
    directory = os.path.join(rootwad, "ObjectData", folder)
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".xml"):
            continue
        data = read_binary_xml(os.path.join(directory, filename))
        adjectives = string_list_field(data, ADJECTIVE_LIST)
        key = string_field(data, DISPLAY_NAME) or ""
        if not adjectives or (key.startswith(MOB_LANG + "_") and INTERACTABLE not in data):
            continue
        yield {
            "template": filename[:-4],
            "name": display_name(rootwad, key, langs) if key else "",
            "name_key": key,
            "icon": icon_name(data, folder),
            "template_id": ids.get(f"ObjectData/{folder}/{filename}", 0),
            "adjectives": adjectives,
        }


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
        zone = zone_of_wad(path)
        for name in templates:
            if name.encode() in data:
                placed[name].append(zone)
    return placed


def npcs(rootwad, folder):
    """The templates of an ObjectData folder that carry a persona, with name, template id and portrait."""
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


@functools.cache
def persona_templates(rootwad):
    """persona -> the object templates of every ObjectData folder that carry it; a zone may place any of them."""
    templates = {}
    for path in sorted(glob.glob(os.path.join(rootwad, "ObjectData", "*", "*.xml"))):
        persona = persona_of(read_binary_xml(path))
        if persona:
            templates.setdefault(persona[:-len(PERSONA_SUFFIX)], []).append(os.path.basename(path)[:-4])
    return templates


def add_mobs_arguments(parser):
    parser.add_argument("folders", nargs="*", default=["CL"], help="ObjectData folders, default CL")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")


def run_mobs(args):
    rows = sorted(row for folder in args.folders for row in mobs(args.rootwad, folder))
    print("display name\ttemplate\ttemplate id\tadjectives")
    for name, template, template_id, adjectives in rows:
        print(f"{name}\t{template}\t{template_id}\t{','.join(adjectives)}")


def run_items(args):
    folder = world(args.world).folder
    print("display name\ticon name\ttemplate\ttemplate id\tadjectives")
    for row in sorted(items(args.rootwad, folder), key=lambda row: (row["name"], row["template"])):
        print("\t".join([row["name"], row["icon"], row["template"], str(row["template_id"]),
                         ",".join(row["adjectives"])]))


def add_npcs_arguments(parser):
    parser.add_argument("--folder", default="CL", help="ObjectData folder of the world's templates, default CL")
    parser.add_argument("--world", default="Celestia", help="zone wad prefix of the world, default Celestia")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    parser.add_argument("--gamedata", default=GAMEDATA_DIR, help="the client's Data/GameData directory")


def run_npcs(args):
    rows = list(npcs(args.rootwad, args.folder))
    placed = zone_placements(args.gamedata, args.world, [row["template"] for row in rows])
    print("persona\tname\tname key\ttemplate\ttemplate id\tportrait\tzones")
    for row in sorted(rows, key=lambda r: r["persona"]):
        print("\t".join([row["persona"], row["name"], row["name_key"], row["template"], str(row["template_id"]),
                         row["portrait"], ",".join(placed[row["template"]])]))


def mobs_main():
    parser = argparse.ArgumentParser(description=MOBS_DESCRIPTION)
    add_mobs_arguments(parser)
    run_mobs(parser.parse_args())


def npcs_main():
    parser = argparse.ArgumentParser(description=NPCS_DESCRIPTION)
    add_npcs_arguments(parser)
    run_npcs(parser.parse_args())

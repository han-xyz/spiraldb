"""Read-only access to the client data the quest tools use: lang files, zone wads and object templates."""
import json
import os
import re
import struct
import zlib

ROOTWAD_DIR = "/kioxia/generator-input/rootwad"
GAMEDATA_DIR = "/kioxia/lutris/wizard101/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Data/GameData"
LANG_SUBDIR = os.path.join("Locale", "en-US")
ZLIB_HEADER = b"\x78\x9c"
MANIFEST_ENTRY = re.compile(rb"(?s)\xbc\x90\xce\xb9(.)(ObjectData/[ -~]+?\.xml)\x60\x00\x00\x00\x3a\x8f\x35\x89(.{4})")
ADJECTIVE_LIST = b"\x06\x16\x73\xbe"
DISPLAY_NAME = b"\x92\xbc\xd8\x91"


def tolerant_load(path):
    with open(path, encoding="utf-8") as f:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", f.read()))


def read_lang(rootwad, name):
    """A lang file as {key: text}; the file is a header line then key, comment, text triplets."""
    with open(os.path.join(rootwad, LANG_SUBDIR, name + ".lang"), "rb") as f:
        lines = f.read().decode("utf-16").split("\r\n")
    return dict(zip(lines[1::3], lines[3::3]))


def lang_exists(rootwad, name):
    return os.path.exists(os.path.join(rootwad, LANG_SUBDIR, name + ".lang"))


def read_wad(path, wanted):
    files = {}
    with open(path, "rb") as f:
        head = f.read(15)
        if head[:5] != b"KIWAD":
            raise SystemExit(f"{path}: not a KIWAD file")
        version, count = struct.unpack_from("<II", head, 5)
        f.seek(15 if version >= 2 else 13)
        table = []
        for _ in range(count):
            offset, size, csize, compressed, _crc, name_len = struct.unpack("<IIIBII", f.read(21))
            name = f.read(name_len)[:-1].decode("latin1")
            if name in wanted:
                table.append((name, offset, size, csize, compressed))
        for name, offset, size, csize, compressed in table:
            f.seek(offset)
            data = f.read(csize if compressed else size)
            files[name] = zlib.decompress(data) if compressed else data
    return files


def zone_strings(gamedata, zone):
    """The printable strings of a zone's gamedata.bin, or None when the zone has no wad."""
    path = os.path.join(gamedata, zone.replace("/", "-") + ".wad")
    if not os.path.exists(path):
        return None
    data = read_wad(path, {"gamedata.bin"}).get("gamedata.bin", b"")
    return {s.decode("latin1") for s in re.findall(rb"[ -~]{4,}", data)}


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

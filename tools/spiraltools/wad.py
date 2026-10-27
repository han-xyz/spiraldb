"""Read-only access to the client's KIWAD archives and the zones and worlds they hold."""
import glob
import os
import re
import struct
import zlib

GAMEDATA_DIR = "/kioxia/lutris/wizard101/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Data/GameData"
ZONE_FILES = frozenset({"gamedata.bin", "triggers.xml", "volumes.xml"})

OBJECT_NAME = b"\xf3\x03\xfa\xca"
PAD_ZONE = b"\xb0\xb8\x66\x5a"
PAD_LOCATION_LIST = b"\xa0\x14\xaf\x8b"
TRIGGER_NAME = b"\x10\x0c\xc9\xb8"
VECTOR_FIELD = rb"(?s)\xa0\x00\x00\x00\x1b\xdc\x7e\x85(.{12})"
NAMED_LOCATION = rb"(?s)([\x01-\x7f])\x00([ -~]{1,127})\xa0\x00\x00\x00\x1b\xdc\x7e\x85(.{12})"
VOLUME_NAME = b"\x8b\x04\xe6\xc6"
VOLUME_POSITION = re.compile(rb"(?s)`\x00\x00\x00\(\xf8\xb3\}(.{4})`\x00\x00\x00\)\xf8\xb3\}(.{4})"
                             rb"`\x00\x00\x00\*\xf8\xb3\}(.{4})")
TELEPORT_VOLUME = "TeleportVol_"
DEFAULT_LOCATION = "Start"


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


def wad_path(gamedata, zone):
    """Grizzleheim/Interiors/GH_Hero_T2 -> <gamedata>/Grizzleheim-Interiors-GH_Hero_T2.wad"""
    return os.path.join(gamedata, zone.replace("/", "-") + ".wad")


def zone_of_wad(path):
    return os.path.basename(path)[:-4].replace("-", "/")


def zone_strings(gamedata, zone):
    """The printable strings of a zone's gamedata.bin, or None when the zone has no wad."""
    path = wad_path(gamedata, zone)
    if not os.path.exists(path):
        return None
    data = read_wad(path, {"gamedata.bin"}).get("gamedata.bin", b"")
    return {s.decode("latin1") for s in re.findall(rb"[ -~]{4,}", data)}


def wide_strings(data, field_hash):
    """Strings stored as <u32 bits><hash><u16 len><bytes>, the gamedata.bin layout."""
    for m in re.finditer(re.escape(field_hash), data):
        start = m.start() - 4
        bits = struct.unpack_from("<I", data, start)[0]
        length = struct.unpack_from("<H", data, m.end())[0]
        if bits == (10 + length) * 8:
            yield start, data[m.end() + 2:m.end() + 2 + length].decode("latin1")


def compact_strings(data, field_hash):
    """Strings stored as <u32 bits><hash><u8 len*2><bytes>, the triggers.xml layout."""
    for m in re.finditer(re.escape(field_hash), data):
        start = m.start() - 4
        bits = struct.unpack_from("<I", data, start)[0]
        length = data[m.end()] // 2
        if bits == (9 + length) * 8:
            yield start, data[m.end() + 1:m.end() + 1 + length].decode("latin1")


class Zone:
    def __init__(self, path, files):
        self.path = path
        self.gamedata = files.get("gamedata.bin", b"")
        self.triggers = files.get("triggers.xml", b"")
        self.volumes = files.get("volumes.xml", b"")
        self.locations = self._named_locations()

    def _named_locations(self):
        found = {}
        for m in re.finditer(NAMED_LOCATION, self.gamedata):
            if m.group(1)[0] == len(m.group(2)):
                found[m.group(2).decode()] = struct.unpack("<3f", m.group(3))
        return found

    def volume_positions(self):
        """{volume: (x, y, z)} for the teleport volumes of volumes.xml."""
        found = {}
        for offset, name in compact_strings(self.volumes, VOLUME_NAME):
            end = offset + 9 + len(name)
            m = VOLUME_POSITION.match(self.volumes, end)
            if name.startswith(TELEPORT_VOLUME) and m:
                found[name[len(TELEPORT_VOLUME):]] = tuple(struct.unpack("<f", g)[0] for g in m.groups())
        return found

    def pads(self):
        """Objects whose teleport behaviour names a destination zone: (name, zone, location, position)."""
        names = list(wide_strings(self.gamedata, OBJECT_NAME))
        locations = list(self._pad_locations())
        vectors = [(m.start(), struct.unpack("<3f", m.group(1))) for m in re.finditer(VECTOR_FIELD, self.gamedata)]
        for offset, zone in wide_strings(self.gamedata, PAD_ZONE):
            owner = [(o, n) for o, n in names if o < offset]
            if not owner:
                continue
            owner_offset, name = owner[-1]
            following = [o for o, _ in names if o > offset]
            end = following[0] if following else len(self.gamedata)
            location = next((n for o, n in locations if offset < o < end), DEFAULT_LOCATION)
            before = [v for o, v in vectors if o < owner_offset]
            yield name, zone, location, before[-1] if before else None

    def _pad_locations(self):
        for m in re.finditer(re.escape(PAD_LOCATION_LIST), self.gamedata):
            count, length = struct.unpack_from("<IH", self.gamedata, m.end())
            if count:
                yield m.start(), self.gamedata[m.end() + 6:m.end() + 6 + length].decode("latin1")

    def triggers_with_events(self):
        names = list(compact_strings(self.triggers, TRIGGER_NAME))
        for i, (offset, name) in enumerate(names):
            end = names[i + 1][0] if i + 1 < len(names) else len(self.triggers)
            span = self.triggers[offset:end]
            events = []
            for m in re.finditer(rb"Enter_[ -~]+", span):
                length = span[m.start() - 1] // 2
                events.append(span[m.start():m.start() + length].decode("latin1"))
            yield name, events


class ZoneWads:
    """The zone wads of a GameData directory, each read once."""

    def __init__(self, gamedata_dir):
        self.dir = gamedata_dir
        self.cache = {}
        self.paths = None

    def wad_path(self, zone):
        return wad_path(self.dir, zone)

    def zone(self, zone):
        if zone not in self.cache:
            path = self.wad_path(zone)
            files = read_wad(path, ZONE_FILES) if os.path.exists(path) else None
            self.cache[zone] = Zone(zone, files) if files is not None else None
        return self.cache[zone]

    def zone_paths(self):
        if self.paths is None:
            self.paths = [zone_of_wad(p) for p in glob.glob(os.path.join(self.dir, "*-*.wad"))]
        return self.paths

    def world_zones(self, world):
        for path in sorted(glob.glob(os.path.join(self.dir, world + "-*.wad"))):
            zone = self.zone(zone_of_wad(path))
            if zone is not None:
                yield zone

    def zones_with_pads_to(self, target):
        needle = target.encode()
        for zone in self.world_zones(target.split("/")[0]):
            if zone.path != target and needle in zone.gamedata and any(z == target for _, z, _, _ in zone.pads()):
                yield zone

    def zones_with_location(self, world, name):
        return [zone for zone in self.world_zones(world) if name in zone.locations]

    def client_zones(self):
        """{world: [Zone]} for every zone wad (one holding a gamedata.bin) in the client."""
        worlds = {}
        for path in sorted(glob.glob(os.path.join(self.dir, "*-*.wad"))):
            zone = self.zone(zone_of_wad(path))
            if zone is not None and zone.gamedata:
                worlds.setdefault(zone.path.split("/")[0], []).append(zone)
        return worlds

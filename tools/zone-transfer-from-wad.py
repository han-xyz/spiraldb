#!/usr/bin/env python3
"""Rebuild ZoneTransfer entries for a zone from the client's zone wad.

See tools/README.md for usage and the location convention.
"""
import argparse
import collections
import glob
import json
import math
import os
import re
import struct
import sys
import zlib

PACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMEDATA_DIR = "/kioxia/lutris/wizard101/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Data/GameData"

OBJECT_NAME = b"\xf3\x03\xfa\xca"
PAD_ZONE = b"\xb0\xb8\x66\x5a"
PAD_LOCATION_LIST = b"\xa0\x14\xaf\x8b"
TRIGGER_NAME = b"\x10\x0c\xc9\xb8"
VECTOR_FIELD = rb"(?s)\xa0\x00\x00\x00\x1b\xdc\x7e\x85(.{12})"
NAMED_LOCATION = rb"(?s)([\x01-\x7f])\x00([ -~]{1,127})\xa0\x00\x00\x00\x1b\xdc\x7e\x85(.{12})"
TELEPORT_VOLUME_EVENT = "Enter_TeleportVol_"
VOLUME_NAME = b"\x8b\x04\xe6\xc6"
VOLUME_POSITION = re.compile(rb"(?s)`\x00\x00\x00\(\xf8\xb3\}(.{4})`\x00\x00\x00\)\xf8\xb3\}(.{4})"
                             rb"`\x00\x00\x00\*\xf8\xb3\}(.{4})")
TELEPORT_VOLUME = "TeleportVol_"
TO_WORD = re.compile(r"(?:^|(?<=[^A-Za-z])|(?<=[a-z]))[Tt]o(?=[A-Z0-9_ \-])|(?<=[_ -])2(?=[_ -])")
FROM_WORD = re.compile(r"(?:^|(?<=[^A-Za-z])|(?<=[a-z]))[Ff]rom(?=[A-Z0-9_ \-])")
MIN_NAME_KEY = 4
MIN_SHORT_TEXT = 3
DEFAULT_LOCATION = "Start"
MAX_PAD_DISTANCE = 1000
MIN_SHORT_NAME = 8
WORLD_ORDER = ("Celestia", "Zafaria", "Avalon", "Azteca", "Khrysalis", "Polaris", "Mirage", "Empyrea", "Karamelle",
               "Lemuria", "Novus", "Wallaru")


def tolerant_load(path):
    with open(path, encoding="utf-8") as f:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", f.read()))


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


class Wads:
    def __init__(self, gamedata_dir):
        self.dir = gamedata_dir
        self.cache = {}
        self.confirmed = {}
        self.paths = None

    def wad_path(self, zone):
        return os.path.join(self.dir, zone.replace("/", "-") + ".wad")

    def zone(self, zone):
        if zone not in self.cache:
            path = self.wad_path(zone)
            files = read_wad(path, {"gamedata.bin", "triggers.xml", "volumes.xml"}) if os.path.exists(path) else None
            self.cache[zone] = Zone(zone, files) if files is not None else None
        return self.cache[zone]

    def zone_paths(self):
        if self.paths is None:
            wads = glob.glob(os.path.join(self.dir, "*-*.wad"))
            self.paths = [os.path.basename(p)[:-4].replace("-", "/") for p in wads]
        return self.paths

    def confirmed_exits(self, zone):
        """{trigger: (zone path, location)} for the exits of the zone that confirmed_exit or neighbour_exit
        places."""
        if zone.path not in self.confirmed:
            parents = list(self.zones_with_pads_to(zone.path))
            found = {}
            for trigger, volume in exit_volumes(zone):
                destination = confirmed_exit(zone, volume, parents, self) or neighbour_exit(zone, trigger, volume, self)
                if destination is not None:
                    found[trigger] = destination
            self.confirmed[zone.path] = found
        return self.confirmed[zone.path]

    def world_zones(self, world):
        for path in sorted(glob.glob(os.path.join(self.dir, world + "-*.wad"))):
            zone = self.zone(os.path.basename(path)[:-4].replace("-", "/"))
            if zone is not None:
                yield zone

    def zones_with_pads_to(self, target):
        needle = target.encode()
        for zone in self.world_zones(target.split("/")[0]):
            if zone.path != target and needle in zone.gamedata and any(z == target for _, z, _, _ in zone.pads()):
                yield zone

    def zones_with_location(self, world, name):
        return [zone for zone in self.world_zones(world) if name in zone.locations]

    def locations_naming(self, target):
        """(zone, location) pairs across the world whose location name contains the target's short name."""
        key = short_key(target)
        return [(zone, name) for zone in self.world_zones(target.split("/")[0]) if zone.path != target
                for name in zone.locations if key in re.sub(r"[^a-z0-9]", "", name.lower())]


def short_key(zone_path):
    """GH_Hero_T8 -> herot8, the form street locations such as FromHeroT8 use."""
    parts = zone_path.rsplit("/", 1)[-1].split("_")
    if len(parts) > 1 and parts[0].isupper() and len(parts[0]) <= 3:
        parts = parts[1:]
    return re.sub(r"[^a-z0-9]", "", "".join(parts).lower())


def entry(trigger, zone, location):
    return {
        "TriggerName": trigger,
        "Teleport": {
            "m_exitTeleporter": 0,
            "m_teleporterTag": 0,
            "m_teleportType": "TELEPORT_STATIC",
            "m_transitionID": 0,
            "m_destinationLoc": location,
            "m_destinationZone": zone,
        },
    }


def exit_volumes(zone):
    """(trigger, volume) for each trigger fired by entering a teleport volume."""
    exits = []
    for trigger, events in zone.triggers_with_events():
        volumes = [e[len(TELEPORT_VOLUME_EVENT):] for e in events if e.startswith(TELEPORT_VOLUME_EVENT)]
        if volumes:
            exits.append((trigger, volumes[0]))
    return exits


def exit_entries(zone, parents, wads, notes):
    """Teleport volumes in the zone, sent to the zone holding a location of the volume's name,
    else, for a zone with one exit, to the one location in the world named after the zone,
    else, with one parent, to the parent's location nearest the pad into the zone (within MAX_PAD_DISTANCE)."""
    exits = exit_volumes(zone)
    out = []
    for trigger, volume in exits:
        named = [p for p in parents if volume in p.locations]
        if not named:
            named = [z for z in wads.zones_with_location(zone.path.split("/")[0], volume) if z.path != zone.path]
        if len(named) == 1:
            out.append(entry(trigger, named[0].path, volume))
            continue
        if not named and len(exits) == 1:
            naming = [(z, n) for z, n in wads.locations_naming(zone.path) if not parents or z in parents]
            if len(naming) == 1:
                out.append(entry(trigger, naming[0][0].path, naming[0][1]))
                continue
        if named or len(parents) != 1 or len(exits) != 1:
            notes.append(f"{zone.path}: exit {trigger!r} skipped, {len(named)} zones name {volume!r}, "
                         f"{len(parents)} parents, {len(exits)} exits")
            continue
        parent = parents[0]
        pad_positions = [pos for _, z, _, pos in parent.pads() if z == zone.path and pos is not None]
        if not pad_positions or not parent.locations:
            notes.append(f"{zone.path}: exit {trigger!r} skipped, no located pad in {parent.path}")
            continue
        location = min(parent.locations, key=lambda n: math.dist(parent.locations[n], pad_positions[0]))
        distance = math.dist(parent.locations[location], pad_positions[0])
        if distance > MAX_PAD_DISTANCE:
            notes.append(f"{zone.path}: exit {trigger!r} skipped, nearest location {location!r} in {parent.path} "
                         f"is {distance:.0f} units from the pad")
            continue
        notes.append(f"{zone.path}: exit {trigger!r} -> {parent.path} {location!r}, {distance:.0f} units from the pad")
        out.append(entry(trigger, parent.path, location))
    return out


def pad_entries(zone):
    return [entry(name, dest, location) for name, dest, location, _ in zone.pads() if dest != zone.path]


def stated_pad_entries(zone):
    """Every pad that names a destination zone, the zone itself included (a teleport within the zone)."""
    return [entry(name, dest, location) for name, dest, location, _ in zone.pads() if dest]


def knows(street, interior):
    """The street's wad names the interior: its full path, or its last path segment when that is distinctive."""
    short = interior.path.rsplit("/", 1)[-1].encode()
    return interior.path.encode() in street.gamedata or (
        len(short) >= MIN_SHORT_NAME and (short in street.gamedata or short in street.triggers))


def inbound_pad_position(street, interior):
    return next((pos for _, z, _, pos in street.pads() if z == interior.path and pos is not None), None)


def exit_candidates(zone, volume, parents, wads):
    """{(zone path, location): zone}: the world's locations named after the volume; with a single exit, also the
    world's locations named after the zone and each parent's location nearest its pad into the zone."""
    world = zone.path.split("/")[0]
    out = {(z.path, volume): z for z in wads.zones_with_location(world, volume) if z.path != zone.path}
    if len(exit_volumes(zone)) != 1:
        return out
    out.update({(z.path, name): z for z, name in wads.locations_naming(zone.path)})
    for parent in parents:
        pad = inbound_pad_position(parent, zone)
        if pad is None or not parent.locations:
            continue
        nearest = min(parent.locations, key=lambda n: math.dist(parent.locations[n], pad))
        if math.dist(parent.locations[nearest], pad) <= MAX_PAD_DISTANCE:
            out[(parent.path, nearest)] = parent
    return out


def confirmed_exit(zone, volume, parents, wads):
    """(zone path, location) for an interior's exit when one candidate's wad names the interior back; with several,
    the one nearest its pad into the interior. None for a zone outside Interiors, one with derived zones (gauntlet
    rooms, variants), or no single choice."""
    if "/Interiors/" not in zone.path or any(p.startswith(zone.path + "_") for p in wads.zone_paths()):
        return None
    children = {z for _, z, _, _ in zone.pads()}
    confirmed = [(key, street) for key, street in exit_candidates(zone, volume, parents, wads).items()
                 if street.path not in children and knows(street, zone)]
    if len(confirmed) == 1:
        return confirmed[0][0]
    by_pad = [(math.dist(street.locations[key[1]], pad), key) for key, street in confirmed
              if (pad := inbound_pad_position(street, zone)) is not None]
    return min(by_pad)[1] if by_pad else None


def name_key(zone_path):
    """AV_Z13_KeepOfGanelon -> keepofganelon: the zone's name without world prefix and zone number."""
    parts = zone_path.rsplit("/", 1)[-1].split("_")
    if len(parts) > 1 and parts[0].isupper() and len(parts[0]) <= 3:
        parts = parts[1:]
    if len(parts) > 1 and re.fullmatch(r"Z\d+[a-z]?\d*", parts[0]):
        parts = parts[1:]
    return re.sub(r"[^a-z0-9]", "", "".join(parts).lower())


def destination_text(name):
    """The part of a trigger name after its last "To"; "" for a name with "From", which names where one came from."""
    if FROM_WORD.search(name):
        return ""
    return re.sub(r"[^a-z0-9]", "", TO_WORD.split(name)[-1].lower())


def names_zone(name, zone):
    """The trigger name sends to the zone: the destination text is the zone's key or its end (To_Hub for
    EM_Z00_Aeriel_HUB), contains a key of MIN_NAME_KEY characters or more, or is the numbered end of the zone's name
    (To_80_03 for KH_Gauntlet80_03)."""
    key, text = name_key(zone.path), destination_text(name)
    last = re.sub(r"[^a-z0-9]", "", zone.path.rsplit("/", 1)[-1].lower())
    if len(text) >= MIN_NAME_KEY and re.search(r"\d", text) and last.endswith(text):
        return True
    return key.endswith(text) and len(text) >= MIN_SHORT_TEXT or (len(key) >= MIN_NAME_KEY and key in text)


def neighbours_named(zone, trigger, volume, wads):
    """The world's zones the exit's trigger or volume name sends to: those whose key is the destination text, else
    those whose key is not part of a longer named key. A key that several zones of the world share counts only with
    the zone's full last path segment in the name (ToDS_Tier1ExteriorPreview1, not MS_Tier1_Exterior_Preview)."""
    world = [z for z in wads.world_zones(zone.path.split("/")[0]) if z.path != zone.path and z.gamedata]
    shared = {k for k, n in collections.Counter(name_key(z.path) for z in world).items() if n > 1}
    text = re.sub(r"[^a-z0-9]", "", (trigger + volume).lower())
    named = [z for z in world if (names_zone(trigger, z) or names_zone(volume, z)) and (
        name_key(z.path) not in shared or re.sub(r"[^a-z0-9]", "", z.path.rsplit("/", 1)[-1].lower()) in text)]
    exact = [z for z in named if name_key(z.path) in (destination_text(trigger), destination_text(volume))]
    if exact:
        return exact
    return [z for z in named if not any(name_key(z.path) != name_key(o.path) and name_key(z.path) in name_key(o.path)
                                        for o in named)]


def neighbour_exit(zone, trigger, volume, wads):
    """(zone path, location) for an exit whose name sends to one neighbour that names the zone back, by an exit of
    its own or a location (FromMandoria). The landing is the neighbour's one location naming the zone, else its
    location nearest the volume of its exit back (within MAX_PAD_DISTANCE). None otherwise."""
    confirmed = []
    for neighbour in neighbours_named(zone, trigger, volume, wads):
        back = [v for t, v in exit_volumes(neighbour) if names_zone(t, zone) or names_zone(v, zone)]
        key = name_key(zone.path)
        arrivals = [n for n in neighbour.locations
                    if len(key) >= MIN_NAME_KEY and key in re.sub(r"[^a-z0-9]", "", n.lower())]
        if back or arrivals:
            confirmed.append((neighbour, back, arrivals))
    if len(confirmed) != 1:
        return None
    neighbour, back, arrivals = confirmed[0]
    if len(arrivals) == 1:
        return neighbour.path, arrivals[0]
    positions = [p for v in back if (p := neighbour.volume_positions().get(v)) is not None]
    candidates = arrivals or list(neighbour.locations)
    if not positions or not candidates:
        return None
    nearest = min(candidates, key=lambda n: math.dist(neighbour.locations[n], positions[0]))
    if math.dist(neighbour.locations[nearest], positions[0]) > MAX_PAD_DISTANCE:
        return None
    return neighbour.path, nearest


def safe_pads(source, entries, wads, covered, review):
    """The pads of the source zone whose location the destination zone's wad names and whose destination has a
    way out: a ZoneTransfer file from before the run, no teleport volume, or a confirmed exit. The rest go to
    review."""
    out = []
    for e in entries:
        zone, location = e["Teleport"]["m_destinationZone"], e["Teleport"]["m_destinationLoc"]
        destination = wads.zone(zone)
        if destination is None or location not in destination.locations:
            review.append((source, e["TriggerName"], f"pad to {zone} {location!r}: no such location in that wad"))
        elif (zone != source and zone not in covered and exit_volumes(destination)
              and not wads.confirmed_exits(destination)):
            review.append((source, e["TriggerName"], f"pad to {zone} {location!r}: its exits are withheld"))
        else:
            out.append(e)
    return out


def exit_review(zone, parents, wads):
    """(zone, trigger, candidates) for each exit: the wad names no destination for a teleport volume, so the
    exit_entries guess and each parent's Start are listed for a person to choose from."""
    notes = []
    guessed = {e["TriggerName"]: e["Teleport"] for e in exit_entries(zone, parents, wads, notes)}
    rows = []
    for trigger, _ in exit_volumes(zone):
        candidates = []
        if trigger in guessed:
            candidates.append(f"{guessed[trigger]['m_destinationZone']} {guessed[trigger]['m_destinationLoc']!r}")
        candidates += [f"{p.path} {DEFAULT_LOCATION!r}" for p in parents]
        rows.append((zone.path, trigger, "; ".join(dict.fromkeys(candidates)) or "none"))
    return rows


def inbound_entries(street, zone):
    out = [entry(name, zone.path, location) for name, dest, location, _ in street.pads() if dest == zone.path]
    if out:
        return out
    for trigger, events in street.triggers_with_events():
        doors = [e[len("Enter_"):] for e in events if e[len("Enter_"):] in zone.locations]
        if doors:
            out.append(entry(trigger, zone.path, doors[0]))
    return out


def zone_transfer_files():
    return {tolerant_load(p)["ZoneName"]: p for p in sorted(glob.glob(os.path.join(PACK, "ZoneTransfer", "*.json")))}


def new_file_path(zone_name):
    """WizardZoneDatas_<last segment>.json, widened by parent segments while the name is taken."""
    segments = zone_name.split("/")
    for n in range(1, len(segments) + 1):
        path = os.path.join(PACK, "ZoneTransfer", f"WizardZoneDatas_{'_'.join(segments[-n:])}.json")
        if not os.path.exists(path):
            return path
    raise SystemExit(f"{zone_name}: every file name is taken; name the file by hand")


def render_entry(item):
    return "\n".join("    " + line for line in json.dumps(item, indent=2, ensure_ascii=False).splitlines())


def merge(zone_name, entries, known):
    """Append the entries whose TriggerName the zone's file lacks; returns the names added."""
    path = known.get(zone_name)
    if path is None:
        path = new_file_path(zone_name)
        unique = list({e["TriggerName"]: e for e in entries}.values())
        doc = {"ZoneName": zone_name, "Events": [], "Teleports": unique}
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        known[zone_name] = path
        return [e["TriggerName"] for e in unique]
    present = {t["TriggerName"] for t in tolerant_load(path).get("Teleports", [])}
    added = []
    for e in entries:
        if e["TriggerName"] not in present:
            present.add(e["TriggerName"])
            added.append(e)
    if not added:
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"(\S)\s*\]\s*\}\s*$", text)
    if m is None:
        raise SystemExit(f"{path}: Teleports is not the last key; edit by hand")
    trailing_comma = m.group(1) == ","
    separator = "\n" if trailing_comma else ",\n"
    body = separator.join(render_entry(e) + ("," if trailing_comma else "") for e in added)
    if m.group(1) == "[":
        text = text[:m.start(1)] + "[\n" + body + "\n  ]\n}\n"
    else:
        text = text[:m.end(1)] + separator + body + "\n  ]\n}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return [e["TriggerName"] for e in added]


def quest_zone_refs():
    """Zones the quests send a player to, in the same fields the S10 audit read."""
    refs = {}

    def walk(node, quest):
        if isinstance(node, dict):
            kind = node.get("$type", "").split(",")[0].split(".")[-1]
            zones = [node.get("m_destinationZone")]
            if kind.endswith("GoalTemplate"):
                zones.append(node.get("m_zoneTag"))
            if kind in ("ReqInZone", "ResAddDynaMod"):
                zones.append(node.get("m_zoneName"))
            for z in zones:
                if z:
                    refs.setdefault(z, set()).add(quest)
            for v in node.values():
                walk(v, quest)
        elif isinstance(node, list):
            for v in node:
                walk(v, quest)

    for path in glob.glob(os.path.join(PACK, "QuestTemplates", "questtemplates_*.json")):
        doc = tolerant_load(path)
        walk(doc, doc.get("m_questName", os.path.basename(path)))
    return refs


def check():
    zones = set()
    inbound = set()
    for path in glob.glob(os.path.join(PACK, "ZoneTransfer", "*.json")):
        doc = tolerant_load(path)
        zones.add(doc["ZoneName"])
        inbound.update(t["Teleport"]["m_destinationZone"] for t in doc.get("Teleports", []))
    refs = quest_zone_refs()
    absent = sorted(z for z in refs if z not in zones)
    no_inbound = sorted(z for z in refs if z in zones and z not in inbound)
    for z in absent:
        print(f"absent\t{z}\t{len(refs[z])} quests")
    for z in no_inbound:
        print(f"no-inbound\t{z}\t{len(refs[z])} quests")
    print(f"quest zones absent from ZoneTransfer: {len(absent)} ({sum(len(refs[z]) for z in absent)} quest refs); "
          f"in ZoneTransfer without an inbound teleport: {len(no_inbound)}")


def client_zones(wads):
    """{world: [Zone]} for every zone wad (one holding a gamedata.bin) in the client."""
    worlds = {}
    for path in sorted(glob.glob(os.path.join(wads.dir, "*-*.wad"))):
        zone = wads.zone(os.path.basename(path)[:-4].replace("-", "/"))
        if zone is not None and zone.gamedata:
            worlds.setdefault(zone.path.split("/")[0], []).append(zone)
    return worlds


def plan_world(zones, wads, known, covered, notes, review):
    """Entries for the world's zones without a ZoneTransfer file, and the pads into them from zones with one.
    Exits go in only when confirmed_exit places them, the rest are appended to review; a pad into a zone whose
    exits are all withheld is held back so that no door leads into a zone without its way out."""
    counts = collections.Counter()
    planned = {}
    for zone in zones:
        counts["zones"] += 1
        if zone.path in known:
            counts["covered"] += 1
            continue
        parents = list(wads.zones_with_pads_to(zone.path))
        confirmed = wads.confirmed_exits(zone)
        exits = [row for row in exit_review(zone, parents, wads) if row[1] not in confirmed]
        review.extend(exits)
        counts["withheld exits"] += len(exits)
        counts["exits"] += len(confirmed)
        for parent in parents:
            if parent.path in known:
                present = {t["TriggerName"] for t in tolerant_load(known[parent.path]).get("Teleports", [])}
                proposed = [e for e in inbound_entries(parent, zone) if e["TriggerName"] not in present]
                inbound = safe_pads(parent.path, proposed, wads, covered, review)
                counts["withheld inbound"] += len(proposed) - len(inbound)
                planned.setdefault(parent.path, []).extend(inbound)
                counts["inbound"] += len(inbound)
        stated = stated_pad_entries(zone)
        pads = safe_pads(zone.path, stated, wads, covered, review)
        counts["withheld pads"] += len(stated) - len(pads)
        entries = [entry(trigger, *destination) for trigger, destination in confirmed.items()] + pads
        if entries:
            planned.setdefault(zone.path, []).extend(entries)
            counts["generated"] += 1
            counts["entries"] += len(entries)
        elif exits or stated:
            counts["all withheld"] += 1
            notes.append(f"{zone.path}: skipped, every teleport is in --review")
        else:
            counts["no teleport"] += 1
            notes.append(f"{zone.path}: skipped, the wad has no pad and no teleport volume")
    return planned, counts


def world_order(worlds, known):
    def uncovered(world):
        return sum(zone.path not in known for zone in worlds[world])
    listed = [w for w in WORLD_ORDER if w in worlds]
    return listed + sorted((w for w in worlds if w not in WORLD_ORDER), key=lambda w: (-uncovered(w), w))


def run_all(wads, only_worlds, mode):
    """mode: "dry-run" prints the per-world counts, "apply" also writes, "review" prints the withheld exits."""
    known = zone_transfer_files()
    worlds = client_zones(wads)
    unknown = [w for w in only_worlds if w not in worlds]
    if unknown:
        raise SystemExit(f"no zone wads for {unknown}")
    covered = frozenset(known)
    columns = ("zones", "covered", "generated", "entries", "exits", "inbound", "withheld inbound", "withheld pads",
               "withheld exits", "no teleport", "all withheld")
    if mode != "review":
        print("world\t" + "\t".join(columns))
    total = collections.Counter()
    notes = []
    for world in world_order(worlds, known):
        if only_worlds and world not in only_worlds:
            continue
        review = []
        planned, counts = plan_world(worlds[world], wads, known, covered, notes, review)
        total.update(counts)
        if mode == "review":
            for row in review:
                print("\t".join(row))
            continue
        print(world + "\t" + "\t".join(str(counts[c]) for c in columns))
        if mode == "apply":
            for target, entries in planned.items():
                if entries:
                    merge(target, entries, known)
    if mode != "review":
        print("total\t" + "\t".join(str(total[c]) for c in columns))
    for note in notes:
        print(note, file=sys.stderr)


def check_all_zones(wads):
    known = zone_transfer_files()
    missing = collections.Counter()
    for world, zones in sorted(client_zones(wads).items()):
        for zone in zones:
            if zone.path not in known:
                missing[world] += 1
                print(f"missing\t{zone.path}")
    for world, n in missing.most_common():
        print(f"{world}\t{n} zones without a ZoneTransfer file")
    print(f"client zones without a ZoneTransfer file: {sum(missing.values())}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zones", nargs="*", help="zone paths, e.g. Grizzleheim/Interiors/GH_Hero_T2")
    parser.add_argument("--apply", action="store_true", help="append the entries to the ZoneTransfer files")
    parser.add_argument("--street", nargs="?", const="", default=None,
                        help="also add the inbound entry to this street's file (bare: the zone's discovered parent)")
    parser.add_argument("--check", action="store_true", help="list quest zones absent from ZoneTransfer")
    parser.add_argument("--all-zones", action="store_true", help="with --check: every client zone without a file")
    parser.add_argument("--all", action="store_true", help="every client zone wad without a ZoneTransfer file")
    parser.add_argument("--world", action="append", default=[], help="with --all: only this world (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="with --all: print the per-world counts only")
    parser.add_argument("--review", action="store_true",
                        help="with --all: list the withheld exits and their candidate destinations")
    parser.add_argument("--gamedata", default=GAMEDATA_DIR, help="the client's Data/GameData directory")
    args = parser.parse_args()
    if args.check:
        if args.all_zones:
            check_all_zones(Wads(args.gamedata))
        else:
            check()
        return
    if args.all:
        modes = [m for m, on in (("dry-run", args.dry_run), ("apply", args.apply), ("review", args.review)) if on]
        if len(modes) != 1:
            parser.error("--all takes one of --dry-run, --apply or --review")
        run_all(Wads(args.gamedata), args.world, modes[0])
        return
    if not args.zones:
        parser.error("give a zone path or --check")
    wads = Wads(args.gamedata)
    known = zone_transfer_files()
    notes = []
    result = {}
    for zone_name in args.zones:
        zone = wads.zone(zone_name)
        if zone is None:
            notes.append(f"{zone_name}: skipped, no wad at {wads.wad_path(zone_name)}")
            continue
        if args.street:
            street = wads.zone(args.street)
            if street is None:
                raise SystemExit(f"--street {args.street}: no wad at {wads.wad_path(args.street)}")
            parents = [street]
        else:
            parents = list(wads.zones_with_pads_to(zone_name))
        planned = {zone_name: pad_entries(zone) + exit_entries(zone, parents, wads, notes)}
        if not planned[zone_name]:
            notes.append(f"{zone_name}: no entry for the zone itself")
        if args.street is not None:
            for street in parents:
                inbound = inbound_entries(street, zone)
                if not inbound:
                    notes.append(f"{zone_name}: no pad or door in {street.path} leads here")
                planned.setdefault(street.path, []).extend(inbound)
        for target, entries in planned.items():
            if not entries:
                continue
            if args.apply:
                added = merge(target, entries, known)
                print(f"{target}: added {added}" if added else f"{target}: nothing new")
            else:
                result.setdefault(target, []).extend(entries)
    if not args.apply:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    for note in notes:
        print(note, file=sys.stderr)


if __name__ == "__main__":
    main()

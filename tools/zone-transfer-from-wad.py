#!/usr/bin/env python3
"""Rebuild ZoneTransfer entries for a zone from the client's zone wad.

See tools/README.md for usage and the location convention.
"""
import argparse
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
DEFAULT_LOCATION = "Start"
MAX_PAD_DISTANCE = 1000


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
        self.locations = self._named_locations()

    def _named_locations(self):
        found = {}
        for m in re.finditer(NAMED_LOCATION, self.gamedata):
            if m.group(1)[0] == len(m.group(2)):
                found[m.group(2).decode()] = struct.unpack("<3f", m.group(3))
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

    def wad_path(self, zone):
        return os.path.join(self.dir, zone.replace("/", "-") + ".wad")

    def zone(self, zone):
        if zone not in self.cache:
            path = self.wad_path(zone)
            files = read_wad(path, {"gamedata.bin", "triggers.xml"}) if os.path.exists(path) else None
            self.cache[zone] = Zone(zone, files) if files is not None else None
        return self.cache[zone]

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


def exit_entries(zone, parents, wads, notes):
    """Teleport volumes in the zone, sent to the zone holding a location of the volume's name,
    else, for a zone with one exit, to the one location in the world named after the zone,
    else, with one parent, to the parent's location nearest the pad into the zone (within MAX_PAD_DISTANCE)."""
    exits = []
    for trigger, events in zone.triggers_with_events():
        volumes = [e[len(TELEPORT_VOLUME_EVENT):] for e in events if e.startswith(TELEPORT_VOLUME_EVENT)]
        if volumes:
            exits.append((trigger, volumes[0]))
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


def render_entry(item):
    return "\n".join("    " + line for line in json.dumps(item, indent=2, ensure_ascii=False).splitlines())


def merge(zone_name, entries, known):
    """Append the entries whose TriggerName the zone's file lacks; returns the names added."""
    path = known.get(zone_name)
    if path is None:
        path = os.path.join(PACK, "ZoneTransfer", f"WizardZoneDatas_{zone_name.rsplit('/', 1)[-1]}.json")
        if os.path.exists(path):
            raise SystemExit(f"{path} exists for another zone; name the file by hand")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zones", nargs="*", help="zone paths, e.g. Grizzleheim/Interiors/GH_Hero_T2")
    parser.add_argument("--apply", action="store_true", help="append the entries to the ZoneTransfer files")
    parser.add_argument("--street", nargs="?", const="", default=None,
                        help="also add the inbound entry to this street's file (bare: the zone's discovered parent)")
    parser.add_argument("--check", action="store_true", help="list quest zones absent from ZoneTransfer")
    parser.add_argument("--gamedata", default=GAMEDATA_DIR, help="the client's Data/GameData directory")
    args = parser.parse_args()
    if args.check:
        check()
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

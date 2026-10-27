"""Quest specs: loading, the lookups they share, and validation against the client data."""
from ..lang import lang_exists, read_lang, zone_location_keys
from ..pack import tolerant_load, zone_transfer_files
from ..templates import persona_templates, places_template, spell_candidates, template_ids_by_name
from ..wad import read_wad, wad_path, zone_strings

GIVER = "giver"


class SpecError(Exception):
    pass


def location_key(spec, loc):
    """A ZoneLocName key as given, or the key of a 'World|Place' text in ZoneLocName.lang."""
    if not loc or loc.startswith("ZoneLocName_") or "_" in loc and "|" not in loc:
        return loc
    keys = spec["_zone_locations"]
    if loc not in keys:
        raise SpecError(f"{spec['id']}: no ZoneLocName entry reads {loc!r}")
    return "ZoneLocName_" + keys[loc]


def spell_name(item):
    """A reward spell item is a name, or {"spell": name, "school": school} for a spell only that school learns."""
    return item if isinstance(item, str) else item["spell"]


def reward_spells(spec):
    return spec.get("reward", {}).get("spells", [])


def spell_template(spec, name):
    """The (manifest path, template id) of the one spell template a reward name means."""
    candidates = spec["_spell_ids"][name]
    if not candidates:
        raise SpecError(f"{spec['id']}: spell {name!r} has no spell template")
    if len(candidates) > 1:
        raise SpecError(f"{spec['id']}: spell {name!r} matches several templates: "
                        + ", ".join(path for path, _ in candidates))
    return candidates[0]


def load_specs(paths, rootwad):
    specs = [dict(tolerant_load(path), _path=path) for path in paths]
    zone_locations = zone_location_keys(rootwad)
    names = {spell_name(item) for spec in specs for item in reward_spells(spec)}
    spell_ids = {name: spell_candidates(rootwad, name) for name in names}
    successors = {}
    for spec in specs:
        for quest in spec.get("requires", []):
            if isinstance(quest, str):
                successors.setdefault(quest, []).append(spec["id"])
    for spec in specs:
        spec["_zone_locations"] = zone_locations
        spec["_spell_ids"] = spell_ids
        spec.setdefault("successors", successors.get(spec["id"], []))
    return specs


def check_spec(spec, rootwad, gamedata, zone_cache, known_zones):
    problems = []
    lang_name = f"WizQst{spec['lang']}"
    if not lang_exists(rootwad, lang_name):
        return [f"no {lang_name}.lang"]
    lines = read_lang(rootwad, lang_name)
    titles = read_lang(rootwad, "QuestTitle")
    title = spec.get("title", f"QuestTitle_{spec['lang']}")
    if title and title.split("_", 1)[1] not in titles:
        problems.append(f"title {title} not in QuestTitle.lang")
    if not spec.get("dialogs", {}).get("prep"):
        problems.append("no prep line: no NPC offers the quest")
    dialog_lines = [entry for key in ("prep", "underway") for entry in spec.get("dialogs", {}).get(key, [])]
    dialog_lines += [entry for goal in spec["goals"] for entry in goal.get("completion", [])]
    for entry in dialog_lines:
        if entry["line"] and "_" not in entry["line"] and entry["line"] not in lines:
            problems.append(f"line {entry['line']} not in {lang_name}.lang")
    personas = [(spec["giver"]["persona"], spec["giver"]["zone"])]
    personas += [(goal["persona"], goal.get("zone", "")) for goal in spec["goals"] if goal["type"] == "persona"]
    zones = {zone for zone in [spec["giver"]["zone"]] + [goal.get("zone") for goal in spec["goals"]] if zone}
    for zone in sorted(zones):
        if zone not in known_zones:
            problems.append(f"zone {zone} has no ZoneTransfer file")
    for persona, zone in personas:
        if persona == GIVER or not zone:
            continue
        if zone not in zone_cache:
            zone_cache[zone] = zone_strings(gamedata, zone)
        if zone_cache[zone] is None:
            problems.append(f"zone {zone} has no wad")
        elif not is_placed(persona, zone, rootwad, gamedata, zone_cache):
            problems.append(f"persona {persona} not placed in {zone}")
    for goal in spec["goals"]:
        try:
            location_key(spec, goal.get("loc", ""))
        except SpecError as e:
            problems.append(str(e))
    for item in reward_spells(spec):
        try:
            spell_template(spec, spell_name(item))
        except SpecError as e:
            problems.append(str(e))
    return problems


def is_placed(persona, zone, rootwad, gamedata, zone_cache):
    """Whether the zone names the persona or one of its templates, or places one of them by template id."""
    names = [persona, *persona_templates(rootwad).get(persona, [])]
    if any(s.startswith(name) for name in names for s in zone_cache[zone]):
        return True
    if (zone, "gamedata.bin") not in zone_cache:
        zone_cache[zone, "gamedata.bin"] = read_wad(wad_path(gamedata, zone), {"gamedata.bin"}).get("gamedata.bin", b"")
    ids = template_ids_by_name(rootwad)
    return any(places_template(zone_cache[zone, "gamedata.bin"], ids.get(name, 0)) for name in names)


def check(specs, rootwad, gamedata):
    zone_cache = {}
    known_zones = set(zone_transfer_files())
    failed = 0
    for spec in specs:
        problems = check_spec(spec, rootwad, gamedata, zone_cache, known_zones)
        failed += bool(problems)
        print(f"{spec['id']}: {'ok' if not problems else ''}")
        for problem in problems:
            print("  " + problem)
    return failed

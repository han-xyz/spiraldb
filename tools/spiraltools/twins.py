"""Boss twins: the hidden NPC a boss tower places beside the boss mob, shown by a quest dynamod on the kill."""
import math
import os
import re
import struct
from collections import namedtuple

from .lang import ROOTWAD_DIR
from .pack import PACK, QUEST_TEMPLATES_DIR, parse_tolerant, quest_template_paths, render
from .templates import DISPLAY_NAME, display_name, persona_of, read_binary_xml, string_field, template_ids
from .wad import GAMEDATA_DIR, OBJECT_NAME, read_wad, wad_path, wide_strings

DESCRIPTION = ("List the boss twins of every bounty quest: the hidden placed NPC sharing the boss's display name and "
               "its hidden companions; --apply shows them when the kill completes.")

BOUNTY_TYPES = ("GOAL_TYPE_BOUNTY", "GOAL_TYPE_BOUNTYCOLLECT")
TEMPLATE_ID = re.compile(rb"(?s)\x80\x00\x00\x00\xaf\xa9\xc8\x25(.{8})")
LOCATION = re.compile(rb"(?s)\xa0\x00\x00\x00\x1b\xdc\x7e\x85(.{12})")
START_STATE = b"\xca\xf8\x27\x81"
UNDETECTABLE = b"\x85\x71\xb1\x71"
SPAWN_REQUIREMENTS = b"\x66\x63\xa2\x89"
NPC_BEHAVIOR = b"NPCBehavior"
ADJECTIVE_SUFFIX = ".AdjRef"
COMPANION_RANGE = 600.0
TWIN = "twin"
DYNAMOD_TYPE = "Imcodec.ObjectProperty.TypeCache.ResAddDynaMod, Imcodec.ObjectProperty"

PlacedObject = namedtuple("PlacedObject", "tag template_id location undetectable start_state has_requirements")
Template = namedtuple("Template", "name display_key display_name persona is_npc")
BountyCase = namedtuple("BountyCase", "goal zone mob_key adjectives")
Fix = namedtuple("Fix", "reveal_goal zone tags")


def bounty_cases(quest):
    """Each bounty goal with its zone: its own, else the nearest earlier goal's."""
    goals = quest.get("m_goals") or []
    cases = []
    for index, bounty in enumerate(goals):
        if bounty.get("m_goalType") not in BOUNTY_TYPES:
            continue
        zone = next((g["m_destinationZone"] for g in reversed(goals[:index + 1]) if g.get("m_destinationZone")), None)
        cases.append(BountyCase(bounty["m_goalName"], zone,
                                (bounty.get("m_tallyCounter") or {}).get("m_descriptor2", ""),
                                bounty.get("m_npcAdjectives") or []))
    return cases


def placed_objects(gamedata):
    """The placed objects of a zone's gamedata.bin, one per m_templateID property."""
    starts = [(m.start(), struct.unpack("<Q", m.group(1))[0]) for m in TEMPLATE_ID.finditer(gamedata)]
    objects = []
    for i, (start, template_id) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(gamedata)
        span = gamedata[start:end]
        location = LOCATION.search(span)
        tag = next((text for _, text in wide_strings(span, OBJECT_NAME)), "")
        state = next((text for _, text in wide_strings(span, START_STATE)), "")
        undetectable = span.find(UNDETECTABLE)
        requirements = span.find(SPAWN_REQUIREMENTS)
        objects.append(PlacedObject(
            tag, template_id, struct.unpack("<3f", location.group(1)) if location else None,
            undetectable >= 0 and bool(span[undetectable + 4] & 1), state,
            requirements >= 0 and span[requirements + 4:requirements + 8] != b"\x00\x00\x00\x00"))
    return objects


class Templates(dict):
    """template id -> Template, read from the root wad's ObjectData on first use."""

    def __init__(self, rootwad):
        super().__init__()
        self.rootwad = rootwad
        self.paths = {template_id: path for path, template_id in template_ids(rootwad).items()}
        self.langs = {}

    def __missing__(self, template_id):
        path = self.paths.get(template_id)
        if path is None:
            self[template_id] = Template("", "", "", None, False)
            return self[template_id]
        data = read_binary_xml(os.path.join(self.rootwad, path))
        persona = persona_of(data)
        key = string_field(data, DISPLAY_NAME) or ""
        self[template_id] = Template(os.path.basename(path)[:-4], key, self.text(key) if key else "", persona,
                                     persona is not None or NPC_BEHAVIOR in data)
        return self[template_id]

    def text(self, key):
        return display_name(self.rootwad, key, self.langs)


def is_twin(template, mob_key, mob_name, adjectives):
    if not template.is_npc:
        return False
    names = {a.removesuffix(ADJECTIVE_SUFFIX) for a in adjectives}
    persona = (template.persona or "").removesuffix("_Persona")
    named_like_mob = (bool(mob_key) and template.display_key == mob_key) or (
        bool(mob_name) and template.display_name == mob_name)
    return named_like_mob or template.name in names or persona in names


def find_twins(objects, templates, mob_key, mob_name, adjectives):
    """(twins, companions): NPCs named like the boss (by key or by text), and hidden NPCs without requirements
    beside a twin."""
    twins = [o for o in objects if is_twin(templates[o.template_id], mob_key, mob_name, adjectives)]
    companions = [o for o in objects
                  if o not in twins and o.undetectable and not o.has_requirements and templates[o.template_id].is_npc
                  and any(
                      o.location and t.location and math.dist(o.location, t.location) <= COMPANION_RANGE
                      for t in twins)]
    return twins, companions


def reveal(tag, zone):
    return {"$type": DYNAMOD_TYPE, "m_dynaModClientTag": tag, "m_dynaModRemove": False,
            "m_useQuestAsOriginator": False, "m_dynaModState": "", "m_zoneName": zone, "m_bShowsObject": True,
            "m_persist": True, "m_requirements": None}


def is_hide(result, tags, zone):
    """A dynamod of the hide-on-entry pattern: it names the object without showing it or giving it a state."""
    return (result.get("$type") == DYNAMOD_TYPE and result["m_dynaModClientTag"] in tags
            and result.get("m_zoneName") == zone and not result.get("m_bShowsObject")
            and not result.get("m_dynaModState"))


def result_lists(node):
    if isinstance(node, dict):
        if isinstance(node.get("m_results"), list):
            yield node
        for value in node.values():
            yield from result_lists(value)
    elif isinstance(node, list):
        for value in node:
            yield from result_lists(value)


def shown_tags(quest):
    return {r["m_dynaModClientTag"] for holder in result_lists(quest) for r in holder["m_results"]
            if r.get("$type") == DYNAMOD_TYPE and r.get("m_bShowsObject")}


def apply_fixes(path, fixes):
    """Show each fix's objects when its bounty completes, skipping tags the quest already shows, and drop the
    hide-on-entry dynamods of the tags it shows. A file whose layout differs from pack.py's render by more than
    whitespace (trailing commas) is refused."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    quest = parse_tolerant(text)
    in_layout = re.sub(r"\s", "", render(quest)) == re.sub(r"\s", "", text)
    shown = shown_tags(quest)
    goals = {g["m_goalName"]: g for g in quest["m_goals"]}
    added = []
    for fix in fixes:
        tags = [tag for tag in fix.tags if tag not in shown]
        if not tags:
            continue
        for holder in result_lists(quest):
            holder["m_results"] = [r for r in holder["m_results"] if not is_hide(r, tags, fix.zone)]
        results = goals[fix.reveal_goal].get("m_completeResults") or {"m_results": []}
        results["m_results"] = (results.get("m_results") or []) + [reveal(tag, fix.zone) for tag in tags]
        goals[fix.reveal_goal]["m_completeResults"] = results
        shown.update(tags)
        added += tags
    if added and not in_layout:
        raise SystemExit(f"{path}: not in the pack's JSON layout; edit by hand")
    if added:
        with open(path, "w", encoding="utf-8") as f:
            f.write(render(quest) if text.endswith("\n") else render(quest).rstrip("\n"))
    return added


def zone_objects(gamedata, zone, cache):
    if zone not in cache:
        path = wad_path(gamedata, zone)
        cache[zone] = (placed_objects(read_wad(path, {"gamedata.bin"}).get("gamedata.bin", b""))
                       if os.path.exists(path) else None)
    return cache[zone]


def describe(objects, templates):
    return ", ".join(f"{o.tag} ({templates[o.template_id].name}, {templates[o.template_id].display_key})"
                     for o in objects) or "-"


def run(args):
    templates = Templates(args.rootwad)
    zones = {}
    print("quest\tzone\tmob key\ttwins\tcompanions\treveal goal\tverdict\thidden NPCs of the zone")
    for path in sorted(quest_template_paths(QUEST_TEMPLATES_DIR)):
        with open(path, encoding="utf-8") as f:
            quest = parse_tolerant(f.read())
        fixes = []
        for case in bounty_cases(quest):
            objects = zone_objects(args.gamedata, case.zone, zones) if case.zone else None
            mob_name = templates.text(case.mob_key) if case.mob_key else ""
            twins, companions = find_twins(objects or [], templates, case.mob_key, mob_name, case.adjectives)
            hidden = [o for o in objects or [] if o.undetectable and templates[o.template_id].is_npc]
            if objects and not twins and not hidden:
                continue
            verdict = verdict_of(case, objects, twins)
            print("\t".join([quest["m_questName"], case.zone or "-", case.mob_key or "-", describe(twins, templates),
                             describe(companions, templates), case.goal, verdict,
                             describe(hidden, templates) if not twins else "-"]))
            if verdict == TWIN:
                fixes.append(Fix(case.goal, case.zone, [o.tag for o in twins + companions]))
        if args.apply and fixes:
            added = apply_fixes(path, fixes)
            if added:
                print(f"applied\t{os.path.relpath(path, PACK)}\t{','.join(added)}")


def verdict_of(case, objects, twins):
    """TWIN only for one hidden twin that nothing else gates; a visible match is a stand-in the quest needs."""
    if case.zone is None:
        return "no zone"
    if objects is None:
        return "no zone wad"
    if not twins:
        return "no twin, hidden NPCs in the zone"
    if len({o.template_id for o in twins}) > 1:
        return "several candidates"
    if not all(o.undetectable for o in twins):
        return "visible match, not hidden"
    if any(o.start_state or o.has_requirements for o in twins):
        return "gated by start state or requirements"
    return TWIN


def add_arguments(parser):
    parser.add_argument("--apply", action="store_true", help="write the dynamod results into the quest files")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    parser.add_argument("--gamedata", default=GAMEDATA_DIR, help="the client's Data/GameData directory")

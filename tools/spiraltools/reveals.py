"""Persona reveals: show a persona goal's NPC when every placement of it in the goal's zone is m_bUndetectable."""
from collections import namedtuple

from .lang import ROOTWAD_DIR
from .pack import QUEST_TEMPLATES_DIR, parse_tolerant, quest_template_paths
from .templates import PERSONA_SUFFIX, persona_templates
from .twins import DYNAMOD_TYPE, Fix, Templates, apply_and_print, goal_zone, result_lists, zone_objects
from .wad import GAMEDATA_DIR

DESCRIPTION = ("List the persona goals whose NPC is placed only hidden (m_bUndetectable) in the goal's zone and that "
               "no quest shows; --apply shows those placements when the goal activates.")

PERSONA_GOAL = "GOAL_TYPE_PERSONA"
REVEAL_ON_ACTIVATE = "m_activateResults"
REVEAL = "reveal"
REVEAL_SEVERAL = "reveal, several placements"

PersonaCase = namedtuple("PersonaCase", "goal zone persona")


def persona_cases(quest):
    """Each persona goal with its zone: its own, else the nearest earlier goal's."""
    goals = quest.get("m_goals") or []
    return [PersonaCase(g["m_goalName"], goal_zone(goals, index),
                        (g.get("m_personaName") or "").removesuffix(PERSONA_SUFFIX.decode()))
            for index, g in enumerate(goals) if g.get("m_goalType") == PERSONA_GOAL]


def persona_fix(case, objects, templates, shown_in_pack):
    """(verdict, Fix or None) for a persona goal given its zone's placed objects and the (zone, tag) pairs that some
    quest of the pack shows. Persona goals carry no location, so several hidden placements are all shown."""
    persona = case.persona + PERSONA_SUFFIX.decode()
    placements = [o for o in objects if templates[o.template_id].persona == persona]
    if not placements:
        return "not placed in the zone", None
    if any(not o.undetectable for o in placements):
        return "visible", None
    if any((case.zone, o.tag) in shown_in_pack for o in placements):
        return "shown by a quest", None
    verdict = REVEAL if len(placements) == 1 else REVEAL_SEVERAL
    return verdict, Fix(case.goal, REVEAL_ON_ACTIVATE, case.zone, [o.tag for o in placements])


def shown_in(quests):
    return {(r.get("m_zoneName"), r["m_dynaModClientTag"]) for quest in quests for holder in result_lists(quest)
            for r in holder["m_results"] if r.get("$type") == DYNAMOD_TYPE and r.get("m_bShowsObject")}


def run(args):
    templates = Templates(args.rootwad)
    known = persona_templates(args.rootwad)
    quests = {}
    for path in sorted(quest_template_paths(QUEST_TEMPLATES_DIR)):
        with open(path, encoding="utf-8") as f:
            quests[path] = parse_tolerant(f.read())
    shown = shown_in(quests.values())
    zones = {}
    print("quest\tgoal\tzone\tpersona\tverdict\ttags")
    for path, quest in quests.items():
        fixes = []
        for case in persona_cases(quest):
            objects = zone_objects(args.gamedata, case.zone, zones) if case.zone else None
            if case.persona not in known:
                verdict, fix = "persona unknown", None
            elif case.zone is None:
                verdict, fix = "no zone", None
            elif objects is None:
                verdict, fix = "no zone wad", None
            else:
                verdict, fix = persona_fix(case, objects, templates, shown)
            if verdict == "visible":
                continue
            print("\t".join([quest["m_questName"], case.goal, case.zone or "-", case.persona or "-", verdict,
                             ",".join(fix.tags) if fix else "-"]))
            if fix:
                fixes.append(fix)
        if args.apply and fixes:
            apply_and_print(path, fixes)


def add_arguments(parser):
    parser.add_argument("--apply", action="store_true", help="write the reveals into the quest files")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    parser.add_argument("--gamedata", default=GAMEDATA_DIR, help="the client's Data/GameData directory")

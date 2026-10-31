"""Quest templates and their drop tables, generated from one JSON spec per quest."""
import argparse
import datetime
import json
import os
import sys

from ..lang import ROOTWAD_DIR
from ..pack import PACK, quest_output_paths, tolerant_load, write_unless_same
from ..wad import GAMEDATA_DIR
from .spec import GIVER, SpecError, check, load_specs, location_key, reward_spells, spell_name, spell_template

DESCRIPTION = "Generate quest templates and their drop tables from one JSON spec per quest."
TYPE = "Imcodec.ObjectProperty.TypeCache.{}, Imcodec.ObjectProperty"
PERSONA_SUFFIX = "_Persona"
VOLUME_EVENT = "Enter_"
GARDENING_SPELL_FOLDER = "Spells/Gardening Spells"
AUTHOR = "questgen"
# Median quest reward of the pack's worlds by level floor: WC, KT, MB, MS, DS drop tables.
REWARD_BANDS = ((40, 3805, 103), (30, 2445, 88), (20, 1722, 68), (10, 630, 43), (0, 112, 15))
GOAL_TITLES = {
    "persona": "WizardQuestGoals_TalkNPC",
    "bounty": "WizardQuestGoals_Kill",
    "bountycollect": "WizardQuestGoals_KillCollect",
    "waypoint": "WizardQuestGoals_ExploreZone",
    "usage": "WizardQuestGoals_UseItem",
}


def ki_hash(text):
    """KingsIsle's string id, the value of m_goalNameID for the goal's original name."""
    result, shift = 0, 0
    for byte in text.encode():
        result ^= ((byte - 32) << shift) & 0xFFFFFFFF
        if shift > 24:
            result ^= (byte - 32) >> (32 - shift)
            if shift >= 27:
                shift -= 32
        shift += 5
    return (-result) & 0x7FFFFFFF if result & 0x80000000 else result


def original_goal_name(number):
    return "Goal" if number == 1 else f"Goal {number - 1}"


def dialog_entry(spec, speaker, line):
    persona = spec["giver"]["persona"] if speaker == GIVER else speaker
    info = spec.get("personas", {}).get(persona, {})
    return {
        "$type": TYPE.format("NPCDialogEntry"),
        "m_personaName": persona + PERSONA_SUFFIX if persona else "",
        "m_nameOverride": "",
        "m_nameSTKey": None,
        "m_guiDisplay": "",
        "m_maxTimeSeconds": -1,
        "m_invisible": False,
        "m_requirements": None,
        "m_dialog": line_key(spec, line),
        "m_picture": info.get("portrait", ""),
        "m_soundFile": "",
        "m_action": "",
        "m_dialogEvent": "",
        "m_actorTemplateID": info.get("template_id", 0),
        "m_cameraName": "",
        "m_interpolationDuration": 1.0,
        "m_cameraOffsetX": 0.0,
        "m_cameraOffsetY": 0.0,
        "m_cameraOffsetZ": 0.0,
        "m_pitch": 0.0,
        "m_yaw": 0.0,
        "m_roll": 0.0,
        "m_cameraShakeType": "",
        "m_cameraShakeDuration": 0.0,
        "m_cameraShakeAmplitude": 0.0,
        "m_bypassCameraOnReview": True,
        "m_cameraZoneName": "",
        "m_duration": 0.0,
        "m_delay": 0.0,
        "m_cameraHidePlayers": 2,
        "m_walkAwayNpcTemplateID": 0,
        "m_walkAwayExitDirectionInDegrees": 0.0,
        "m_walkAwayFadeTime": 0.0,
        "m_walkAwayUseCurrentFacing": False,
        "m_standInPlayerTag": "",
        "m_fadeOutCamera": False,
        "m_snapCameraToPlayerAtExit": False,
        "m_secondaryCameraName": "",
        "m_secondaryInterpolationDuration": 0.0,
        "m_npcStandInList": [],
        "m_dialogAnimationList": [],
        "m_dialogTurningList": [],
        "m_npcYawOffsetInDegrees": 0.0,
        "m_allowPlayerToMove": False,
        "m_soundEffectFile": "",
        "m_musicFile": "",
        "m_nonStackableMusic": False,
        "m_nonRepeatableMusic": False,
        "m_playMusicAtSFXVolume": False,
        "m_soundEffectDelay": 0.0,
        "m_musicDelay": 0.0,
        "m_musicFadeTime": 3.0,
        "m_dontReleaseCameraAtExit": False,
        "m_disableBackButton": False,
        "m_enableExitButton": False,
        "m_cameraFadeType": "",
        "m_cameraFadeTime": 0.5,
        "m_idleAnimation": "",
        "m_spamTime": 1.0,
        "m_playSoundIfSpamming": True,
        "m_playMusicIfSpamming": True,
        "m_stopMusicFadeTime": 0.0,
        "m_restartMusicFadeTime": 0.0,
        "m_meetsRequirements": True,
        "m_secondaryCameraInitalDelay": 0.0,
        "m_displayButtonsOnTimedDialog": False,
    }


def line_key(spec, line):
    """A line of the quest's own WizQst file by its key, or a full lang key from another file."""
    return line if not line or "_" in line else f"WizQst{spec['lang']}_{line}"


def dialog(spec, tag, lines):
    return {
        "m_dialogTag": tag,
        "m_dialogEntries": [dialog_entry(spec, entry["speaker"], entry["line"]) for entry in lines],
        "m_madlibs": None,
        "m_dialogEvents": None,
        "m_noAggroWhileDialogIsUp": False,
        "m_noAggroNoDelay": False,
    }


def dialog_list(dialogs):
    return {"$type": TYPE.format("ActorDialogList"), "m_dialogs": dialogs}


def tally(percent, descriptor, descriptor2, count):
    return {"m_percentChance": percent, "m_descriptor": descriptor, "m_descriptor2": descriptor2, "m_count": count,
            "m_tallyResults": {"m_results": []}}


def goal_base(spec, goal, number, template_class):
    title = goal.get("title", GOAL_TITLES[goal["type"]])
    return {
        "$type": TYPE.format(template_class),
        "m_goalName": f"{number}_{title}",
        "m_goalNameID": ki_hash(original_goal_name(number)),
        "m_goalTitle": title,
        "m_goalUnderway": None,
        "m_hyperlink": None,
        "m_completeText": None,
        "m_completeResults": {"m_results": []},
        "m_goalRequirements": None,
        "m_tallyCounter": None,
        "m_locationName": location_key(spec, goal.get("loc", "")),
        "m_displayImage1": goal.get("portrait", ""),
        "m_displayImage2": "",
        "m_clientTags": goal.get("client_tags", []),
        "m_genericEvents": [],
        "m_autoQualify": False,
        "m_autoComplete": False,
        "m_destinationZone": goal.get("zone", ""),
        "m_dialogList": None,
        "m_goalType": "",
        "m_noQuestHelper": False,
        "m_petOnlyQuest": False,
        "m_activateResults": {"m_results": []},
        "m_hideGoalFloatyText": False,
        "m_behaviors": None,
    }


def persona_goal(spec, goal, number):
    built = goal_base(spec, goal, number, "PersonaGoalTemplate")
    persona = spec["giver"]["persona"] if goal["persona"] == GIVER else goal["persona"]
    if "portrait" not in goal:
        built["m_displayImage1"] = spec.get("personas", {}).get(persona, {}).get("portrait", "")
    completion = goal.get("completion", [])
    built["m_dialogList"] = dialog_list([dialog(spec, "Completion", completion)] if completion else [])
    built["m_goalType"] = "GOAL_TYPE_PERSONA"
    built["m_personaName"] = persona
    built["m_usePatron"] = False
    return built


def bounty_goal(spec, goal, number):
    built = goal_base(spec, goal, number, "BountyGoalTemplate")
    collect = goal["type"] == "bountycollect"
    built["m_tallyCounter"] = tally(goal.get("chance", 1.0), goal.get("descriptor", ""), goal.get("target", ""),
                                    goal["count"])
    built["m_goalType"] = "GOAL_TYPE_BOUNTYCOLLECT" if collect else "GOAL_TYPE_BOUNTY"
    built["m_bountyTotal"] = goal["count"]
    built["m_bountyType"] = "BT_MOB_KILL"
    built["m_npcAdjectives"] = goal["mobs"]
    return built


def waypoint_goal(spec, goal, number):
    built = goal_base(spec, goal, number, "WaypointGoalTemplate")
    built["m_tallyCounter"] = tally(1.0, goal.get("descriptor", ""), "", 0)
    built["m_goalType"] = "GOAL_TYPE_WAYPOINT"
    built["m_zoneEntry"] = "volume" not in goal
    built["m_zoneTag"] = goal["zone"]
    built["m_proximityTag"] = VOLUME_EVENT + goal["volume"] if "volume" in goal else ""
    built["m_zoneExit"] = False
    return built


def usage_goal(spec, goal, number):
    built = goal_base(spec, goal, number, "ScavengeGoalTemplate")
    built["m_tallyCounter"] = tally(1.0, goal.get("descriptor", ""), "", goal["count"])
    built["m_goalType"] = "GOAL_TYPE_USAGE"
    built["m_itemAdjectives"] = goal["items"]
    built["m_itemTotal"] = goal["count"]
    built["m_hideGoal"] = False
    built["m_requiresMagicWeavingSchool"] = ""
    return built


GOAL_BUILDERS = {
    "persona": persona_goal,
    "bounty": bounty_goal,
    "bountycollect": bounty_goal,
    "waypoint": waypoint_goal,
    "usage": usage_goal,
}


def steps(goal_names, goals):
    """Goals grouped into sequential steps; a goal with with_previous joins the step before it."""
    grouped = []
    for name, goal in zip(goal_names, goals):
        if goal.get("with_previous") and grouped:
            grouped[-1].append(name)
        else:
            grouped.append([name])
    return grouped


def goal_logic(grouped):
    return [{
        "m_goalsAND": step,
        "m_goalsOR": [],
        "m_goalsToAdd": grouped[i + 1] if i + 1 < len(grouped) else [],
        "m_completeQuest": i + 1 == len(grouped),
        "m_requiredORCount": 1,
    } for i, step in enumerate(grouped)]


def has_entry(quest, entry, registry, negate):
    return {"$type": TYPE.format("ReqHasEntry"), "m_entryName": entry, "m_displayName": None,
            "m_isQuestRegistry": registry, "m_questName": quest, "m_applyNOT": negate, "m_operator": "ROP_AND"}


def school_of_focus(school):
    return {"$type": TYPE.format("ReqSchoolOfFocus"), "m_magicSchool": school, "m_applyNOT": False,
            "m_operator": "ROP_AND"}


def requirements(spec):
    """A `requires` entry is a quest id, or {"school": School} for a quest only that school's wizards take."""
    reqs = [school_of_focus(entry["school"]) if isinstance(entry, dict) else has_entry(entry, "Complete", True, False)
            for entry in spec.get("requires", [])]
    if "min_level" in spec:
        reqs.append({"$type": TYPE.format("ReqMagicLevel"), "m_magicSchool": "", "m_numericValue": spec["min_level"],
                     "m_operatorType": "OPERATOR_GREATER_THAN_EQ", "m_applyNOT": False, "m_operator": "ROP_AND"})
    reqs += [has_entry(quest, "Completed", False, True) for quest in spec.get("successors", [])]
    if not reqs:
        return None
    return {"$type": TYPE.format("RequirementList"), "m_requirements": reqs, "m_applyNOT": False, "m_operator": "ROP_AND"}


def learn_spell(spec, item):
    """A ResLearnSpell by template id; a gardening spell is a ResAddSpell by name, as the pack grants them."""
    requirements = None
    if not isinstance(item, str):
        requirements = {"m_requirements": [school_of_focus(item["school"])], "m_applyNOT": False,
                        "m_operator": "ROP_AND"}
    path, template_id = spell_template(spec, spell_name(item))
    if os.path.dirname(path) == GARDENING_SPELL_FOLDER:
        return {"$type": TYPE.format("ResAddSpell"), "m_templateID": 0, "m_spellName": spell_name(item),
                "m_requirements": requirements}
    return {"$type": TYPE.format("ResLearnSpell"), "m_templateID": template_id, "m_requirements": requirements}


def quest_template(spec):
    goals = spec["goals"]
    built_goals = [GOAL_BUILDERS[goal["type"]](spec, goal, n) for n, goal in enumerate(goals, 1)]
    grouped = steps([goal["m_goalName"] for goal in built_goals], goals)
    quest_dialogs = [dialog(spec, tag, spec.get("dialogs", {}).get(key, []))
                     for tag, key in (("Prep", "prep"), ("Underway", "underway"))
                     if spec.get("dialogs", {}).get(key)]
    return {
        "m_questName": spec["id"],
        "m_questNameID": 0,
        "m_questTitle": spec.get("title", f"QuestTitle_{spec['lang']}"),
        "m_questInfo": None,
        "m_questPrep": None,
        "m_questUnderway": None,
        "m_questComplete": None,
        "m_startGoals": grouped[0],
        "m_goals": built_goals,
        "m_startResults": {"m_results": []},
        "m_endResults": {"m_results": [{"$type": TYPE.format("ResDropTable"), "m_tableName": spec["id"], "m_maxRolls": 1},
                                       *(learn_spell(spec, item) for item in reward_spells(spec))]},
        "m_requirements": requirements(spec),
        "m_prepRequirements": None,
        "m_pruneRequirements": None,
        "m_prepAlways": False,
        "m_clientTags": None,
        "m_goalLogic": goal_logic(grouped),
        "m_questLevel": spec.get("level", 0),
        "m_questRepeat": 0,
        "m_onStartQuestScript": "",
        "m_onEndQuestScript": "",
        "m_dialogList": dialog_list(quest_dialogs),
        "m_missionDoors": None,
        "m_dynaMods": None,
        "m_isHidden": False,
        "m_outdated": spec.get("outdated", False),
        "m_noQuestHelper": False,
        "m_mainline": spec.get("mainline", False),
        "m_defaultDialogAnimation": None,
        "m_skipQHAutoSelect": False,
        "m_questEffectInfoList": None,
        "m_forceInteraction": False,
        "m_checkInventoryForCrafting": False,
        "m_playAsYourPetNPC": False,
        "m_activityType": "ACTIVITY_NotActivity",
        "m_behaviors": None,
    }


def reward(spec):
    given = spec.get("reward", {})
    level = spec.get("level", 0)
    _, band_xp, band_gold = next(band for band in REWARD_BANDS if level >= band[0])
    return given.get("xp", band_xp), given.get("gold", band_gold)


def drop_table(spec, stamp):
    xp, gold = reward(spec)
    return {
        "Name": spec["id"],
        "Description": "",
        "RollChance": 1.0,
        "Weight": 100,
        "NoneChance": 0.0,
        "PityCounter": 0.0,
        "MinGold": gold,
        "MaxGold": gold,
        "ExperienceAmount": xp,
        "TrainingPoints": 0,
        "Items": [],
        "CreatedAt": stamp,
        "ModifiedAt": stamp,
        "CreatedBy": AUTHOR,
        "ModifiedBy": AUTHOR,
    }


def is_others_quest(template_path, table_path):
    """Whether the pack's quest under this path came from elsewhere: captured or built by hand, its drop table not
    questgen's."""
    return os.path.exists(template_path) and (not os.path.exists(table_path)
                                              or tolerant_load(table_path).get("CreatedBy") != AUTHOR)


def generate(specs, apply):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for spec in specs:
        template_path, table_paths = quest_output_paths(spec["id"])
        if spec.get("captured"):
            print(f"{spec['id']}: captured as {spec['captured']}, left alone")
            continue
        if is_others_quest(template_path, table_paths[0]):
            print(f"{spec['id']}: {os.path.relpath(template_path, PACK)} is not questgen's, left alone")
            continue
        template, table = quest_template(spec), drop_table(spec, stamp)
        if not apply:
            xp, gold = reward(spec)
            print(f"{spec['id']}: {len(spec['goals'])} goals, {xp} xp, {gold} gold -> {os.path.relpath(template_path, PACK)}")
            continue
        changed = write_unless_same(template_path, template)
        for path in table_paths:
            changed |= write_unless_same(path, table, ignored=("CreatedAt", "ModifiedAt"))
        print(f"{spec['id']}: {'written' if changed else 'unchanged'}")


def diff(expected, actual, path=""):
    """The paths where two JSON values differ."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                yield f"{path}.{key}: only generated"
            elif key not in expected:
                yield f"{path}.{key}: only in pack"
            else:
                yield from diff(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        for i, (a, b) in enumerate(zip(expected, actual)):
            yield from diff(a, b, f"{path}[{i}]")
    elif expected != actual and not (isinstance(expected, (int, float)) and not isinstance(expected, bool)
                                     and isinstance(actual, (int, float)) and expected == actual):
        yield f"{path}: generated {json.dumps(expected)[:80]} pack {json.dumps(actual)[:80]}"


def compare(specs):
    for spec in specs:
        template_path, _ = quest_output_paths(spec["id"])
        differences = list(diff(quest_template(spec), tolerant_load(template_path)))
        print(f"== {spec['id']}: {len(differences)} differences")
        for line in differences:
            print("  " + line)


def add_arguments(parser):
    parser.add_argument("specs", nargs="+", help="quest spec JSON files")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the templates and drop tables")
    mode.add_argument("--check", action="store_true", help="validate the specs against the client data")
    mode.add_argument("--diff", action="store_true", help="compare the generated templates with the pack's")
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    parser.add_argument("--gamedata", default=GAMEDATA_DIR, help="the client's Data/GameData directory")


def run(args):
    specs = load_specs(args.specs, args.rootwad)
    try:
        if args.check:
            sys.exit(1 if check(specs, args.rootwad, args.gamedata) else 0)
        if args.diff:
            compare(specs)
            return
        generate(specs, args.apply)
    except SpecError as e:
        sys.exit(str(e))


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_arguments(parser)
    run(parser.parse_args())

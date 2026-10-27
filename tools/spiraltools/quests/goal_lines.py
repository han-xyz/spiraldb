"""How a wiki goal line reads: its verb, the kind of goal it asks for, its target text, and names without the
wiki's notes."""
import re

KILL_VERBS = {"defeat", "fight", "battle", "beat", "vanquish", "duel", "slay", "kill", "subdue", "banish"}
TALK_VERBS = {"talk", "speak", "meet", "visit", "report", "ask", "greet", "tell", "consult", "seek"}
MOVE_VERBS = {"go", "enter", "explore", "search", "return", "exit", "continue", "head", "travel", "journey",
              "proceed", "venture", "leave", "climb", "descend", "ride", "sail", "fly", "teleport", "flee",
              "escape", "walk", "run", "board", "press"}
# Verbs whose object is a thing to click even when the wiki links it as an NPC (an Examine [NPC:Stellar Protector]).
ITEM_VERBS = {"use", "activate", "examine", "inspect", "interact", "photomance", "photograph", "open", "light",
              "place", "plant", "fish", "release", "repair", "fix", "read", "restore", "remove", "clear", "collect",
              "gather", "recover", "retrieve", "craft", "destroy"}
FIND_VERBS = {"find", "locate", "look", "investigate", "check", "survey", "track"}
PERSON_VERBS = {"rescue", "free", "save", "escort", "follow", "approach", "help", "assist", "deliver", "give",
                "bring", "show", "wake", "pursue", "confront", "protect", "heal", "aid", "warn", "catch", "chase",
                "take"} | FIND_VERBS
GOAL_VERBS = KILL_VERBS | TALK_VERBS | MOVE_VERBS | ITEM_VERBS | PERSON_VERBS

PHOTOMANCE = re.compile(r"^Press Z to Photomance\b", re.I)
VERB_HINT = re.compile(r"^\(?(\w+)\)?(?:\s+\((\w+)[^)]*\))?")
PARTICLE = re.compile(r"^(?:(?:to|into|for|through|out|up|on|off|with|at|back|onto|inside|exploring|"
                      r"investigating|pressing|onward|the|a|an)\b\s*)+", re.I)
NOTE = re.compile(r"\s*\([^)]*\)")
COUNT = re.compile(r"^\d+\s+")
LINK = re.compile(r"\[\w+:([^\]]*)\]")


def strip_notes(name):
    """A name without the wiki's parenthesised notes: school, rank, world tags, where the NPC stands."""
    return NOTE.sub("", name).strip()


def verb_of(text):
    """The goal's verb, lowercase: a parenthesised hint after it wins (`Locate (Collect)` reads as collect), and a
    verb in parentheses is read without them (`(Enter) the Cave`)."""
    text = PHOTOMANCE.sub("Photomance", text)
    match = VERB_HINT.match(text)
    if not match:
        return ""
    hint = (match.group(2) or "").lower()
    return hint if hint in GOAL_VERBS else match.group(1).lower()


def is_goal_line(text):
    return verb_of(text) in GOAL_VERBS


def target_text(text):
    """What the goal line names after its verb: no verb, particle, article, count or note."""
    text = PHOTOMANCE.sub("Photomance", text)
    rest = VERB_HINT.sub("", text, count=1)
    return COUNT.sub("", PARTICLE.sub("", NOTE.sub("", rest).strip())).strip()


def place_readings(text):
    """The place names a target may mean, the most specific first: the whole, then each side of an " in "."""
    parts = [part.strip() for part in re.split(r"\s+(?:in|at|inside|near|of)\s+(?:the\s+)?", text) if part.strip()]
    return list(dict.fromkeys([text] + parts))


def goal_kind(verb, text, npcs, creatures, places):
    """persona, bounty, waypoint or usage: what the line asks the player to do."""
    if verb in KILL_VERBS or (verb == "confront" and creatures):
        return "bounty"
    if verb in TALK_VERBS:
        return "persona"
    if npcs and not creatures and verb not in ITEM_VERBS:
        return "persona"
    if verb in MOVE_VERBS or (verb == "take" and " to " in text):
        return "waypoint"
    if places and verb in FIND_VERBS:
        return "waypoint"
    return "usage"


def repeated(groups):
    """Goal groups as (line, sub-items, times): a line repeated on consecutive lines is one goal done that often."""
    merged = []
    for line, subs in groups:
        if merged and not subs and not merged[-1][1] and merged[-1][0] == line:
            merged[-1][2] += 1
        else:
            merged.append([line, subs, 1])
    return merged


"""How a wiki goal line reads: its verb, the kind of goal it asks for, its target text, and names without the
wiki's notes."""
import re

KILL_VERBS = {"defeat", "fight", "battle", "beat", "vanquish", "duel", "slay", "kill", "subdue", "banish", "smoosh",
              "challenge", "stop"}
TALK_VERBS = {"talk", "speak", "meet", "visit", "report", "ask", "greet", "tell", "consult", "seek", "update",
              "convince", "negotiate"}
MOVE_VERBS = {"go", "enter", "explore", "search", "return", "exit", "continue", "head", "travel", "journey",
              "proceed", "venture", "leave", "climb", "descend", "ride", "sail", "fly", "teleport", "flee",
              "escape", "walk", "run", "board", "press", "scout"}
# Verbs whose object is a thing to click even when the wiki links it as an NPC (an Examine [NPC:Stellar Protector]).
ITEM_VERBS = {"use", "activate", "examine", "inspect", "interact", "photomance", "photograph", "open", "light",
              "place", "plant", "fish", "release", "repair", "fix", "read", "restore", "remove", "clear", "collect",
              "gather", "recover", "retrieve", "craft", "destroy", "study", "tune", "unlock", "chop", "trim", "water",
              "install", "paint", "purify", "restart", "write", "play", "break", "tear", "unravel", "get", "procure",
              "pick"}
# Item verbs whose line names an item to collect, which stays a usage goal even when no item reads it.
COLLECT_VERBS = {"collect", "gather", "recover", "retrieve", "craft", "get", "procure", "pick"}
FIND_VERBS = {"find", "locate", "look", "investigate", "check", "survey", "track"}
PERSON_VERBS = {"rescue", "free", "save", "escort", "follow", "approach", "help", "assist", "deliver", "give",
                "bring", "show", "wake", "pursue", "confront", "protect", "heal", "aid", "warn", "catch", "chase",
                "take"} | FIND_VERBS
GOAL_VERBS = KILL_VERBS | TALK_VERBS | MOVE_VERBS | ITEM_VERBS | PERSON_VERBS
# Verbs of lines that move the player somewhere without being read as waypoints: one they do not reach stays blocked.
WAY_VERBS = {"reach", "ascend", "cross", "pass", "infiltrate", "assault", "sneak", "jump", "lead", "launch"}
# Person verbs that move the player when what they name is no NPC (`Follow the Trail of Papers`).
FOLLOW_VERBS = {"follow", "approach", "pursue", "chase"}

PHOTOMANCE = re.compile(r"^Press Z to Photomance\b", re.I)
# What the pet does is the goal: `Use Pet Mode to find Wally`, `(Use it to) Search for Bartleby`.
PET_MODE = re.compile(r"^(?:Use Pet Mode to|\(Use it to\))\s+", re.I)
VERB_HINT = re.compile(r"^\(?(\w+)\)?(?:\s+\((\w+)[^)]*\))?")
PARTICLE = re.compile(r"^(?:(?:to|into|for|through|out|up|on|off|with|at|back|onto|inside|exploring|"
                      r"investigating|pressing|onward|the|a|an)\b\s*)+", re.I)
NOTE = re.compile(r"\s*\([^)]*\)")
COUNT = re.compile(r"^\d+\s+")
DESTINATION_NOTE = re.compile(r"\((?:enter|into|in|inside)\s+(?:the\s+)?([^)]+)\)", re.I)
DESTINATION = re.compile(r"\s(?:to|into)\s+(?:the\s+)?(.+)$", re.I)
MAKE_WAY = re.compile(r"^make (?:your|their) way\b", re.I)
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


def destinations(verb, text):
    """Where a line no item reads sends the player: a parenthesised note entering a place (`(Enter Rage Dream)`),
    else what follows its " to " or " into " (`Lead the Nobles to Dasein`). None for an item verb, whose place is
    where the item stands."""
    if verb in ITEM_VERBS:
        return []
    after = DESTINATION.search(NOTE.sub("", text))
    return DESTINATION_NOTE.findall(text) + ([after.group(1).strip()] if after else [])


def unread_field(verb, text):
    """The needs_review field of a line nothing reads, by what its verb asks for."""
    if verb in MOVE_VERBS | WAY_VERBS | FIND_VERBS | FOLLOW_VERBS or MAKE_WAY.match(text):
        return "goal.waypoint"
    if verb in ITEM_VERBS:
        return "goal.usage"
    if verb in PERSON_VERBS:
        return "goal.persona"
    return "goal.unknown-verb"


def goal_kind(verb, text, npcs, creatures):
    """persona, bounty, waypoint or usage: what the line asks the player to do."""
    if verb in KILL_VERBS or (verb == "confront" and creatures):
        return "bounty"
    if verb in TALK_VERBS:
        return "persona"
    if npcs and not creatures and verb not in ITEM_VERBS:
        return "persona"
    if verb in MOVE_VERBS or (verb == "take" and " to " in text):
        return "waypoint"
    return "usage"


def repeated(groups):
    """Goal groups as (line, sub-items, times): a line repeated on consecutive lines, once with how often."""
    merged = []
    for line, subs in groups:
        if merged and not subs and not merged[-1][1] and merged[-1][0] == line:
            merged[-1][2] += 1
        else:
            merged.append([line, subs, 1])
    return merged


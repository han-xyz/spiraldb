"""The spiraltools command line: one subcommand per tool, and `check` for what the pack still lacks."""
import argparse
import glob
import os

from . import crownshop, templates, zones
from .lang import ROOTWAD_DIR
from .pack import PACK, QUEST_SPECS_DIR, duplicate_trigger_names
from .quests import archive, generate
from .quests.spec import check as check_specs
from .quests.spec import load_specs
from .wad import GAMEDATA_DIR
from .worlds import WORLDS, world

QUEST_MODES = {
    "check": "validate the specs against the client data",
    "generate": "list what the specs would write; --apply writes the templates and drop tables",
    "diff": "compare the generated templates with the pack's",
}
ARCHIVE_MODES = {
    "enumerate": "list the world's quests from the archived categories",
    "fetch": "download the listed quest pages into the cache",
    "parse": "write a questgen spec per cached quest page",
}


def world_specs(name):
    return sorted(glob.glob(os.path.join(QUEST_SPECS_DIR, world(name).name.lower(), "*.json")))


def run_quests(args, parser):
    if not args.specs and not args.world:
        parser.error("give spec files or --world")
    args.specs = args.specs or world_specs(args.world)
    if not args.specs:
        parser.error(f"no specs in {os.path.join(QUEST_SPECS_DIR, world(args.world).name.lower())}")
    args.check, args.diff = args.mode == "check", args.mode == "diff"
    args.apply = getattr(args, "apply", False)
    generate.run(args)


def run_archive(args, parser):
    args.enumerate, args.fetch, args.parse = (args.world if args.mode == mode else None for mode in ARCHIVE_MODES)
    archive.run(args)


def run_check(args, parser):
    """Quest zones without ZoneTransfer, repeated TriggerNames, client zones without a file, and failing specs."""
    zones.check()
    duplicates = duplicate_trigger_names()
    for path, names in duplicates.items():
        for name in names:
            print(f"duplicate\t{os.path.relpath(path, PACK)}\t{name}")
    print(f"ZoneTransfer files with a repeated TriggerName: {len(duplicates)}")
    missing = zones.missing_zones(zones.Wads(args.gamedata))
    for name, paths in missing.items():
        if paths:
            print(f"{name}\t{len(paths)} zones without a ZoneTransfer file")
    print(f"client zones without a ZoneTransfer file: {sum(len(paths) for paths in missing.values())}")
    failed = 0
    for registered in WORLDS:
        paths = world_specs(registered.name)
        if paths:
            failed += check_specs(load_specs(paths, args.rootwad), args.rootwad, args.gamedata)
    print(f"specs failing their check: {failed}")
    return 1 if duplicates or failed else 0


def client_arguments(parser):
    parser.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    parser.add_argument("--gamedata", default=GAMEDATA_DIR, help="the client's Data/GameData directory")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    sub = commands.add_parser("zones", help=zones.DESCRIPTION, description=zones.DESCRIPTION)
    zones.add_arguments(sub)
    sub.set_defaults(run=zones.run)

    sub = commands.add_parser("crownshop", help=crownshop.DESCRIPTION, description=crownshop.DESCRIPTION)
    crownshop.add_arguments(sub)
    sub.set_defaults(run=lambda args, _: crownshop.run(args))

    sub = commands.add_parser("mobs", help=templates.MOBS_DESCRIPTION, description=templates.MOBS_DESCRIPTION)
    templates.add_mobs_arguments(sub)
    sub.set_defaults(run=lambda args, _: templates.run_mobs(args))

    sub = commands.add_parser("items", help=templates.ITEMS_DESCRIPTION, description=templates.ITEMS_DESCRIPTION)
    sub.add_argument("world", help=f"one of {', '.join(w.name for w in WORLDS)}")
    sub.add_argument("--rootwad", default=ROOTWAD_DIR, help="the unpacked root wad")
    sub.set_defaults(run=lambda args, _: templates.run_items(args))

    sub = commands.add_parser("npcs", help=templates.NPCS_DESCRIPTION, description=templates.NPCS_DESCRIPTION)
    templates.add_npcs_arguments(sub)
    sub.set_defaults(run=lambda args, _: templates.run_npcs(args))

    quests = commands.add_parser("quests", help=generate.DESCRIPTION, description=generate.DESCRIPTION)
    modes = quests.add_subparsers(dest="mode", required=True)
    for mode, text in QUEST_MODES.items():
        sub = modes.add_parser(mode, help=text, description=text)
        sub.add_argument("specs", nargs="*", help="quest spec JSON files")
        sub.add_argument("--world", help="every spec of tools/quest-specs/<world>")
        if mode == "generate":
            sub.add_argument("--apply", action="store_true", help="write the templates and drop tables")
        client_arguments(sub)
        sub.set_defaults(run=lambda args, _, sub=sub: run_quests(args, sub))

    wiki = commands.add_parser("archive", help=archive.DESCRIPTION, description=archive.DESCRIPTION)
    modes = wiki.add_subparsers(dest="mode", required=True)
    for mode, text in ARCHIVE_MODES.items():
        sub = modes.add_parser(mode, help=text, description=text)
        sub.add_argument("world", help=f"one of {', '.join(w.name for w in WORLDS)}")
        archive.add_cache_argument(sub)
        sub.set_defaults(run=run_archive)

    sub = commands.add_parser("check", help=run_check.__doc__, description=run_check.__doc__)
    client_arguments(sub)
    sub.set_defaults(run=run_check)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.run(args, parser)

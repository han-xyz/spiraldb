import os
import tempfile
import types
import unittest

from client import needs_gamedata
from spiraltools.wad import GAMEDATA_DIR, wad_path
from spiraltools.zones import (Wads, destination_text, entry, exit_entries, inbound_entries, name_key, names_zone,
                               pad_entries)

INTERIOR = "Grizzleheim/Interiors/GH_Hero_T2"
STREET = "Grizzleheim/GH_Hero"


class NameRulesTest(unittest.TestCase):
    def test_name_key_drops_world_prefix_and_zone_number(self):
        self.assertEqual(name_key("Avalon/AV_Z13_KeepOfGanelon"), "keepofganelon")

    def test_destination_text_is_what_follows_the_last_to(self):
        self.assertEqual(destination_text("TeleportTo_Badlands"), "badlands")
        self.assertEqual(destination_text("From_Mandoria_To_Hub"), "")

    def test_names_zone_takes_a_numbered_end(self):
        zone = types.SimpleNamespace(path="Khrysalis/KH_Gauntlet80_03")
        self.assertTrue(names_zone("To_80_03", zone))
        self.assertFalse(names_zone("To_80_04", zone))


@needs_gamedata
class ZoneWadTest(unittest.TestCase):
    """The street GH_Hero and its interior GH_Hero_T2, read from the client into a GameData of their own."""

    def setUp(self):
        directory = tempfile.mkdtemp()
        for zone in (INTERIOR, STREET):
            os.symlink(wad_path(GAMEDATA_DIR, zone), wad_path(directory, zone))
        self.wads = Wads(directory)

    def test_the_street_is_the_interior_parent(self):
        self.assertEqual([z.path for z in self.wads.zones_with_pads_to(INTERIOR)], [STREET])

    def test_the_interior_exit_lands_at_the_street_location_named_after_it(self):
        interior, street = self.wads.zone(INTERIOR), self.wads.zone(STREET)
        notes = []
        self.assertEqual(pad_entries(interior) + exit_entries(interior, [street], self.wads, notes),
                         [entry("ToHeroCamp", STREET, "FromHeroT2")])
        self.assertEqual(notes, [])

    def test_the_street_pad_leads_into_the_interior(self):
        self.assertEqual(inbound_entries(self.wads.zone(STREET), self.wads.zone(INTERIOR)),
                         [entry("TeleportToHeroT2", INTERIOR, "FromHeroCamp")])

    def test_a_zone_without_a_wad_is_none(self):
        self.assertIsNone(self.wads.zone("Grizzleheim/Nowhere"))


if __name__ == "__main__":
    unittest.main()

import unittest
from copy import deepcopy
from src.catalog import resolve_weapon
from src.constants import sockets


class DefaultArtworkTests(unittest.TestCase):
    def setUp(self):
        self.weapon = {
            "uuid": "2f59173c-4bed-b6c3-2191-dea9b58be9c7",
            "displayName": "Melee",
            "defaultSkinUuid": "12cc9ed2-4430-d2fe-3064-f7a19b1ba7c7",
            "displayIcon": "https://media.valorant-api.com/weapons/2f59173c-4bed-b6c3-2191-dea9b58be9c7/displayicon.png",
            "skins": [{
                "uuid": "12cc9ed2-4430-d2fe-3064-f7a19b1ba7c7", "displayName": "Melee",
                "displayIcon": "skin-placeholder",
                "chromas": [{"uuid": "cac83e5c-47a1-3519-5420-1db1fdbc4892", "displayIcon": "chroma-X"}],
            }],
        }

    def resolve(self, skin_id):
        item = {"Sockets": {
            sockets["skin"]: {"Item": {"ID": skin_id}},
            sockets["skin_chroma"]: {"Item": {"ID": "cac83e5c-47a1-3519-5420-1db1fdbc4892"}},
        }}
        return resolve_weapon(self.weapon["uuid"], item, [self.weapon])

    def test_default_melee_uses_knife_instead_of_chroma_x(self):
        record = self.resolve(self.weapon["defaultSkinUuid"].upper())
        self.assertEqual(record["skinDisplayIcon"], self.weapon["displayIcon"])
        self.assertEqual(record["skinDisplayName"], "Melee")

    def test_paid_knife_keeps_its_own_artwork(self):
        custom = deepcopy(self.weapon["skins"][0])
        custom.update(uuid="58442f45-4783-42a2-f4cb-789a27555889", displayName="Custom Knife")
        custom["chromas"][0]["displayIcon"] = "custom-knife-art"
        self.weapon["skins"].append(custom)
        self.assertEqual(self.resolve(custom["uuid"])["skinDisplayIcon"], "custom-knife-art")

    def test_unknown_skin_is_not_assumed_to_be_default(self):
        record = self.resolve("unknown")
        self.assertEqual(record["metadataStatus"], "unknown_skin")
        self.assertIsNone(record["skinDisplayIcon"])


if __name__ == "__main__":
    unittest.main()

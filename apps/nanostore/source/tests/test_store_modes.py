import importlib.util
import unittest
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nanostore_modes", SOURCE_DIR / "nanostore" / "store_modes.py")
MODES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODES)


class StoreModesTest(unittest.TestCase):
    def test_all_supported_profiles_have_operational_contract(self):
        self.assertEqual(set(MODES.STORE_MODES), {"pharmacy", "store", "distributor", "commerce", "food", "services"})
        for profile in MODES.STORE_MODES.values():
            for field in ("name", "catalog", "sales", "primary_action", "tracks_inventory", "show_fiscal"):
                self.assertIn(field, profile)

    def test_unknown_mode_falls_back_to_pharmacy(self):
        key, profile = MODES.resolve_store_mode("unknown")
        self.assertEqual(key, "pharmacy")
        self.assertEqual(profile["name"], "Farmacia")

    def test_services_use_non_inventory_items_and_no_product_invoice(self):
        profile = MODES.STORE_MODES["services"]
        self.assertFalse(profile["tracks_inventory"])
        self.assertFalse(profile["show_fiscal"])


if __name__ == "__main__":
    unittest.main()

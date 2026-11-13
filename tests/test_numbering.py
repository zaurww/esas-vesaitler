"""Inventory-number suggestion (engine/mutate/numbering.py)."""

import unittest

from engine.mutate import suggest_inv_no


def card(inv, cat):
    return {"inv_no": inv, "category": cat}


class SuggestInvNo(unittest.TestCase):
    def test_follows_prefix_used_by_most_cards(self):
        # Found on a live client: one truck moved from nv kept NV-0005, and
        # the suggestion followed it because its counter (5) beat YM's (3).
        rows = [card("NV-0005", "ym"), card("YM-0001", "ym"),
                card("YM-0002", "ym"), card("YM-0003", "ym"),
                card("NV-0019", "nv")]
        self.assertEqual(suggest_inv_no(rows, "ym"), "YM-0004")

    def test_tie_goes_to_higher_counter(self):
        rows = [card("A-0002", "ma"), card("B-0007", "ma")]
        self.assertEqual(suggest_inv_no(rows, "ma"), "B-0008")

    def test_skips_numbers_taken_in_other_categories(self):
        rows = [card("X-0001", "ma"), card("X-0002", "dg")]
        self.assertEqual(suggest_inv_no(rows, "ma"), "X-0003")

    def test_empty_category_falls_back_to_code(self):
        self.assertEqual(suggest_inv_no([card("NV-0001", "nv")], "ym"), "YM-0001")


if __name__ == "__main__":
    unittest.main()

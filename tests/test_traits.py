"""Category traits (engine/rates.py Category): what applies to a category is
read from the category, never decided by comparing its code.

Before the traits, `it`, `qma-m` and `qma-n` were spelled out in some twenty
places, and adding `it` leaked QMA wording into three screens (CLAUDE.md
§10). The guard below fails the moment a code literal comes back.
"""

from __future__ import annotations

import re
import unittest

from tests.support import ROOT, EngineTest, rates


SPECIAL = ("it", "qma-m", "qma-n")
LITERAL = re.compile(r"""(['"])(%s)\1""" % "|".join(re.escape(c) for c in SPECIAL))

# Where the codes legitimately live: the table that defines them, and data
# examples / fixtures that are about a category rather than deciding by one.
ALLOWED = {
    "engine/rates.py",
    "engine/excel.py",            # TEMPLATE_EXAMPLES: a sample row in qma-m
}


class NoCategoryCodesInLogic(unittest.TestCase):

    def test_no_code_compares_against_a_special_category(self):
        offenders = []
        for path in list((ROOT / "engine").rglob("*.py")) \
                + list((ROOT / "web").rglob("*.py")) \
                + list((ROOT / "web" / "static").glob("*.js")) \
                + [ROOT / "ev.py"]:
            rel = path.relative_to(ROOT).as_posix()
            if rel in ALLOWED:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8-sig")
                                     .splitlines(), 1):
                code = line.split("#")[0].split("//")[0]
                if LITERAL.search(code):
                    offenders.append(f"{rel}:{n}: {line.strip()}")
        self.assertEqual(offenders, [], "ask the category's traits instead")


class Traits(EngineTest):

    def test_fixed_asset_categories_get_every_mechanism(self):
        for code in ("bt", "ma", "nv", "ym", "yt", "dg"):
            c = rates.current().by_code[code]
            self.assertTrue(c.coefficient and c.threshold and c.repair_limit_115,
                            code)
            self.assertEqual(c.exclusion, "")

    def test_intangibles_and_lease_repairs_get_none_of_them(self):
        for code in SPECIAL:
            c = rates.current().by_code[code]
            self.assertFalse(c.coefficient or c.threshold or c.repair_limit_115,
                             code)
        self.assertEqual(rates.current().by_code["it"].exclusion, "lease")
        self.assertEqual(rates.current().by_code["qma-m"].exclusion, "qma")

    def test_term_sources(self):
        by = rates.current().by_code
        self.assertEqual((by["qma-m"].term_source, by["qma-m"].term_floor),
                         ("card", 1))
        self.assertEqual((by["it"].term_source, by["it"].term_floor),
                         ("card", 5))
        self.assertEqual(by["qma-n"].term_source, "param:qma_term_unknown")
        self.assertIn(by["qma-n"].term_source[len("param:"):], rates.PARAM_DEFS)

    def test_only_the_lease_repair_needs_confirmation_and_stays_out_of_import(self):
        cats = rates.current().categories
        self.assertEqual([c.code for c in cats if c.needs_confirmation], ["it"])
        self.assertEqual([c.code for c in cats if not c.bulk_import], ["it"])

    def test_an_owner_category_is_a_plain_fixed_asset(self):
        from tests.support import owner_categories
        owner_categories(
            "code\tname_az\tname_ru\tkind\tlaw_ref\tnote\n"
            "iy\tİş heyvanları\t\tev\tVM m.114.3.4\t\n")
        c = rates.current().by_code["iy"]
        self.assertTrue(c.coefficient and c.threshold and c.repair_limit_115)
        self.assertTrue(c.bulk_import)
        self.assertEqual(c.term_source, "")

    def test_a_repair_in_a_category_without_a_limit_is_loud(self):
        """It used to be skipped by `continue` -- the money vanished (§2.1)."""
        from datetime import date
        from tests.support import (D, Repair, asset, client,
                                   owner_categories)
        from engine.calc import CalcError, compute_year
        owner_categories(
            "code\tname_az\tname_ru\tkind\tlaw_ref\tnote\n"
            "iy\tİş heyvanları\t\tev\tVM m.114.3.4\t\n",
            "effective_year\tcategory\tmax_rate\trepair_limit\tnote\n"
            "2001\tiy\t0.20\t\t\n")
        data = client(assets=[asset("A", "iy", "1000", in_year=2024)])
        data.repairs = [Repair(2024, "A", date(2024, 7, 1), D("100"))]
        with self.assertRaises(CalcError):
            compute_year(data, 2024)


if __name__ == "__main__":
    unittest.main()

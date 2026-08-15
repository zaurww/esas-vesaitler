"""The articles that are not just "residual x rate":

  114.8       the 500 / 5% write-off, which spans two years (§5.3-bis)
  115         the repair fund -- limit, deduction, capitalisation (§5.5)
  114.6/7/9   disposal: the residual and the proceeds are two things (§5.5-bis)
"""

from datetime import date

from tests.support import D, EngineTest, Disposal, Repair, WriteOff, asset, \
    card_of, client, opening

from engine.calc import compute_year


class Threshold(EngineTest):
    """§5.3-bis. 114.8 ties the test to the residual at the END of the year,
    which is the same number as the opening balance of the next one. So the
    year that trips the test is not the year anything is written off."""

    def build(self, cost="2000", opening_2025="480"):
        data = client(years=(2024, 2025, 2026))
        data.assets = [asset("A1", "ma", cost, in_year=2024)]
        data.opening_balances = [opening(2025, "A1", opening_2025)]
        return data

    def test_the_year_it_trips_writes_nothing_off(self):
        data = self.build()
        r = compute_year(data, 2024)
        self.assertEqual([c.inv_no for c in r.threshold_cards], [])
        self.assertMoney(r.totals.get("writeoff", D("0")), "0.00")

    def test_the_next_year_offers_the_decision(self):
        r = compute_year(self.build(), 2025)
        self.assertEqual([c.inv_no for c in r.threshold_cards], ["A1"])
        self.assertFalse(card_of(r, "A1").written_off)

    def test_without_a_decision_it_keeps_depreciating(self):
        """Whether that is lawful is §12.6-ter, still open. What must not
        happen is the engine deciding for the taxpayer."""
        r = compute_year(self.build(), 2025)
        self.assertMoney(card_of(r, "A1").depreciation, "96.00")   # 480 x 20%
        self.assertMoney(card_of(r, "A1").writeoff, "0.00")

    def test_with_a_decision_the_whole_base_goes(self):
        data = self.build()
        data.writeoffs = [WriteOff(2025, "A1", "qərar")]
        r = compute_year(data, 2025)
        c = card_of(r, "A1")
        self.assertMoney(c.writeoff, "480.00")
        self.assertMoney(c.depreciation, "0.00")
        self.assertMoney(c.closing, "0.00")

    def test_five_percent_arm_uses_the_original_cost(self):
        """A 100 000 asset at 4 000 is under 5% though far above 500."""
        data = client(years=(2024, 2025))
        data.assets = [asset("A1", "ma", "100000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", "4000")]
        r = compute_year(data, 2025)
        self.assertEqual([c.inv_no for c in r.threshold_cards], ["A1"])

    def test_a_legacy_pool_is_tested_on_500_only(self):
        """No original cost exists for a group residual, so the 5% arm cannot
        apply to it (§6.1)."""
        data = client(years=(2024, 2025))
        pool = asset("P1", "ma", "0", in_year=None, is_legacy_pool=True)
        data.assets = [pool]
        data.opening_balances = [opening(2024, "P1", "4000"),
                                 opening(2025, "P1", "4000")]
        r = compute_year(data, 2025)
        self.assertEqual([c.inv_no for c in r.threshold_cards], [])


class Repairs(EngineTest):
    """§5.5: the limit is per category, the spending is per asset."""

    def test_within_the_limit_everything_is_deductible(self):
        data = client(years=(2024, 2025))
        data.assets = [asset("A1", "ma", "10000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", "10000")]
        data.repairs = [Repair(2025, "A1", None, D("300"))]
        r = compute_year(data, 2025)
        cat = r.categories[0]
        self.assertMoney(cat.repair_limit, "500.00")        # 10 000 x 5%
        self.assertMoney(cat.repair_deductible, "300.00")
        self.assertMoney(cat.repair_capitalized, "0.00")

    def test_the_excess_is_capitalised_into_the_base(self):
        data = client(years=(2024, 2025))
        data.assets = [asset("A1", "ma", "10000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", "10000")]
        data.repairs = [Repair(2025, "A1", None, D("800"))]
        r = compute_year(data, 2025)
        c = card_of(r, "A1")
        self.assertMoney(c.repair_deductible, "500.00")
        self.assertMoney(c.repair_capitalized, "300.00")
        self.assertMoney(c.base, "10300.00")

    def test_the_deductible_part_splits_in_proportion_to_spending(self):
        """Two assets, 3:1 spending, one shared limit."""
        data = client(years=(2024, 2025))
        data.assets = [asset("A1", "ma", "10000", in_year=2024),
                       asset("A2", "ma", "10000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", "10000"),
                                 opening(2025, "A2", "10000")]
        data.repairs = [Repair(2025, "A1", None, D("1500")),
                        Repair(2025, "A2", None, D("500"))]
        r = compute_year(data, 2025)
        cat = r.categories[0]
        self.assertMoney(cat.repair_limit, "1000.00")       # 20 000 x 5%
        self.assertMoney(card_of(r, "A1").repair_deductible, "750.00")
        self.assertMoney(card_of(r, "A2").repair_deductible, "250.00")
        self.assertMoney(card_of(r, "A1").repair_capitalized, "750.00")
        self.assertMoney(card_of(r, "A2").repair_capitalized, "250.00")

    def test_the_limit_follows_the_category(self):
        """Buildings 2%, machinery 5% -- same money, different limit."""
        data = client(years=(2024, 2025))
        data.assets = [asset("B1", "bt", "10000", in_year=2024),
                       asset("M1", "ma", "10000", in_year=2024)]
        data.opening_balances = [opening(2025, "B1", "10000", "bt"),
                                 opening(2025, "M1", "10000")]
        r = compute_year(data, 2025)
        limits = {c.code: c.repair_limit for c in r.categories}
        self.assertMoney(limits["bt"], "200.00")
        self.assertMoney(limits["ma"], "500.00")


class DisposalOutcome(EngineTest):
    """§5.5-bis: 114.6 takes the residual out of the base; 114.7 and 114.9
    are separate lines of the return, not part of depreciation."""

    def dispose(self, proceeds, residual="800"):
        data = client(years=(2024, 2025))
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", residual)]
        data.disposals = [Disposal("A1", date(2025, 5, 1), "realizasiya",
                                   D(proceeds))]
        return compute_year(data, 2025)

    def test_sold_above_residual_is_income_under_114_7(self):
        r = self.dispose("1200")
        self.assertMoney(r.disposal_gain, "400.00")
        self.assertMoney(r.disposal_loss, "0.00")

    def test_sold_below_residual_is_a_deduction_under_114_9(self):
        r = self.dispose("500")
        self.assertMoney(r.disposal_loss, "300.00")
        self.assertMoney(r.disposal_gain, "0.00")

    def test_the_difference_is_not_mixed_into_depreciation(self):
        r = self.dispose("1200")
        self.assertMoney(r.totals["depreciation"], "0.00")
        self.assertMoney(r.totals["disposed"], "800.00")

    def test_it_appears_in_the_declaration_as_its_own_line(self):
        r = self.dispose("1200")
        lines = {ln.article: ln for ln in r.declaration}
        self.assertMoney(lines["m.114.7"].amount, "400.00")
        self.assertEqual(lines["m.114.7"].effect, "income")
        self.assertEqual(lines["m.114.9"].effect, "deduction")

    def test_scrapping_raises_the_144_1_3_question_rather_than_applying_it(self):
        """The reinvestment condition is only checkable by a human (§5.5-bis)."""
        data = client(years=(2024, 2025))
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", "800")]
        data.disposals = [Disposal("A1", date(2025, 5, 1), "leqv", D("100"))]
        r = compute_year(data, 2025)
        self.assertMoney(r.disposal_loss, "700.00")
        self.assertTrue(any("144.1.3" in w for w in r.warnings))


if __name__ == "__main__":
    import unittest
    unittest.main()

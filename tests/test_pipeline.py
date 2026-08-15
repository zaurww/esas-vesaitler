"""The year pipeline (§5.3), its mandatory controls (§5.4) and the way
balances move between years (§6.1).

The balance identity is checked by the engine itself and raises when it does
not hold, so several of these tests would fail loudly rather than quietly --
which is the design (§2.1). They are here anyway: an identity nobody exercises
is an identity nobody knows still holds.
"""

from decimal import Decimal

from tests.support import D, EngineTest, Addition, Disposal, Repair, asset, \
    card_of, client, opening

from engine.calc import CalcError, compute_year


class PipelineOrder(EngineTest):

    def test_acquisition_takes_the_full_annual_rate(self):
        """Bought in December, still a full year of depreciation -- no
        proration (§5.3 step 2)."""
        data = client()
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        r = compute_year(data, 2024)
        self.assertMoney(card_of(r, "A1").depreciation, "200.00")

    def test_addition_joins_the_base_in_full(self):
        """A capital addition enlarges the asset, so unlike a repair it is not
        capped by anything (§4, additions.tsv)."""
        data = client()
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        data.additions = [Addition(2024, "A1", None, D("500"))]
        r = compute_year(data, 2024)
        self.assertMoney(card_of(r, "A1").base, "1500.00")
        self.assertMoney(card_of(r, "A1").depreciation, "300.00")

    def test_disposed_residual_leaves_the_base(self):
        """114.6: the residual of what left is subtracted BEFORE the rate is
        applied, so a disposed asset accrues nothing that year."""
        from datetime import date
        data = client()
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", "800")]
        data.disposals = [Disposal("A1", date(2025, 4, 1), "realizasiya",
                                   D("800"))]
        r = compute_year(data, 2025)
        c = card_of(r, "A1")
        self.assertMoney(c.disposed, "800.00")
        self.assertMoney(c.base, "0.00")
        self.assertMoney(c.depreciation, "0.00")
        self.assertMoney(c.closing, "0.00")

    def test_closing_is_opening_minus_depreciation(self):
        data = client()
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        r = compute_year(data, 2024)
        c = card_of(r, "A1")
        self.assertMoney(c.closing, "800.00")


class BalanceIdentity(EngineTest):
    """§5.4.1: opening + acquisitions + additions + capitalised repair
    - disposed - depreciation - write-offs = closing, per category."""

    def identity(self, cat):
        return (cat.opening + cat.acquisition + cat.addition
                + cat.repair_capitalized - cat.disposed
                - cat.depreciation - cat.writeoff)

    def test_holds_with_everything_happening_at_once(self):
        from datetime import date
        data = client()
        data.assets = [
            asset("A1", "ma", "10000", in_year=2024),
            asset("A2", "ma", "4000", in_year=2024),
            asset("A3", "ma", "2000", in_year=2025),
        ]
        data.opening_balances = [opening(2025, "A1", "8000"),
                                 opening(2025, "A2", "3200")]
        data.additions = [Addition(2025, "A1", None, D("1000"))]
        data.repairs = [Repair(2025, "A1", None, D("3000"))]
        data.disposals = [Disposal("A2", date(2025, 7, 1), "realizasiya",
                                   D("2000"))]
        r = compute_year(data, 2025)
        for cat in r.categories:
            self.assertMoney(self.identity(cat), f"{cat.closing:.2f}",
                             f"kateqoriya {cat.code}")

    def test_totals_are_the_sum_of_the_categories(self):
        data = client()
        data.assets = [asset("A1", "ma", "1000", in_year=2024),
                       asset("A2", "nv", "5000", in_year=2024)]
        r = compute_year(data, 2024)
        self.assertMoney(
            r.totals["depreciation"],
            f"{sum(c.depreciation for c in r.categories):.2f}")


class CarryForward(EngineTest):
    """§6.1: the opening balance resolves per asset, most specific first."""

    def test_chains_from_the_previous_year_without_any_act(self):
        data = client()
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        r = compute_year(data, 2026)
        # 1000 -> 800 -> 640 -> 512
        self.assertMoney(card_of(r, "A1").opening, "640.00")
        self.assertMoney(card_of(r, "A1").closing, "512.00")
        self.assertEqual(card_of(r, "A1").opening_source, "carried")

    def test_an_explicit_row_beats_the_chain(self):
        data = client()
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        data.opening_balances = [opening(2026, "A1", "100")]
        r = compute_year(data, 2026)
        self.assertMoney(card_of(r, "A1").opening, "100.00")
        self.assertEqual(card_of(r, "A1").opening_source, "explicit")

    def test_an_asset_bought_later_does_not_exist_earlier(self):
        data = client()
        data.assets = [asset("A1", "ma", "1000", in_year=2026)]
        r = compute_year(data, 2025)
        self.assertEqual([c.asset_id for c in r.cards], [])

    def test_a_year_without_a_status_refuses_rather_than_assuming_one(self):
        data = client(years=(2024,))
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2025)
        self.assertIn("status", str(e.exception).lower())


class SpentCards(EngineTest):
    """§5.3-bis: an asset whose life ended stays in the report as a zero row.
    It is a record, not a holding."""

    def test_a_fully_depreciated_card_stays_listed_at_zero(self):
        data = client(years=(2024, 2025))
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", "0")]
        r = compute_year(data, 2025)
        c = card_of(r, "A1")
        self.assertTrue(c.retired)
        self.assertMoney(c.depreciation, "0.00")
        self.assertMoney(c.closing, "0.00")

    def test_money_spent_on_a_spent_card_brings_it_back(self):
        """It used to vanish silently, and the repair row with it (§2.1)."""
        data = client(years=(2024, 2025))
        data.assets = [asset("A1", "ma", "1000", in_year=2024)]
        data.opening_balances = [opening(2025, "A1", "0")]
        data.repairs = [Repair(2025, "A1", None, D("400"))]
        r = compute_year(data, 2025)
        c = card_of(r, "A1")
        self.assertFalse(c.retired)
        self.assertMoney(c.repair_actual, "400.00")


if __name__ == "__main__":
    import unittest
    unittest.main()

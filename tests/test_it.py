"""İcarəyə götürülmüş ƏV-in təmiri — art. 115.6-1 (§5.1, §5.3, §10).

Modelled as an ordinary straight-line card, the same branch as `qma-m`
(§5.3), because m.115.6-1 sets its own complete schedule -- a lease
contract's term, floored at 5 years -- outside art. 114 altogether. These
tests mirror test_qma.py's `NotAFixedAsset` class almost line for line: the
same three fixed-asset mechanisms (coefficient, 500/5%, the ordinary art. 115
repair limit) must not reach it, for a DIFFERENT legal reason than a QMA's
(art. 118 vs. a self-contained mechanism outside art. 114), which is why the
refusal is worded differently in calc.py even though the gate itself
(kind == "qma") is shared.

Only the common case of m.115.6-1 is modelled: the leased asset not on the
lessee's own balance, the repair neither reimbursed by the lessor nor offset
against rent. The rarer case -- the leased asset carried on the lessee's OWN
balance (m.115.4, a plain percentage limit) -- is out of scope, decided
19.08.2026 (CLAUDE.md §10).
"""

from datetime import date

from tests.support import (
    D, Disposal, EngineTest, RateElection, Repair, WriteOff, asset, card_of,
    client, opening,
)

from engine.calc import CalcError, compute_year


def leased_repair(aid="I1", cost="5000", in_year=2024, term=5):
    return asset(aid, "it", cost, in_year=in_year, useful_life=term)


class Schedule(EngineTest):
    """m.115.6-1: "bağlanmış müqavilə müddəti ərzində, lakin 5 ildən az
    olmayaraq, illər üzrə mütənasib məbləğlərdə amortizasiya olunmaqla
    gəlirdən çıxılır" -- the same straight line as a known-term QMA, just
    with a 5-year floor and a different article behind it."""

    def build(self, term=5, cost="5000"):
        data = client(years=tuple(range(2024, 2033)), start_year=2024)
        data.assets = [leased_repair(cost=cost, term=term)]
        return data

    def test_the_charge_is_the_same_every_year(self):
        data = self.build()
        for y in range(2024, 2029):
            self.assertMoney(card_of(compute_year(data, y), "I1").depreciation,
                             "1000.00", f"{y}")

    def test_it_lands_on_zero_and_then_archives(self):
        r = compute_year(self.build(), 2028)
        c = card_of(r, "I1")
        self.assertMoney(c.depreciation, "1000.00")
        self.assertMoney(c.closing, "0.00")
        c2 = card_of(compute_year(self.build(), 2029), "I1")
        self.assertTrue(c2.retired)
        self.assertEqual(c2.retired_kind, "amortizasiya")

    def test_a_longer_contract_runs_its_own_length(self):
        """8 years agreed, no floor to apply -- m.115.6-1 sets a MINIMUM,
        not a fixed length."""
        data = self.build(term=8, cost="8000")
        for y in range(2024, 2032):
            self.assertMoney(card_of(compute_year(data, y), "I1").depreciation,
                             "1000.00", f"{y}")

    def test_a_term_under_five_years_is_caught_reading_it_back(self):
        """The floor is enforced at entry (storage.check_qma), so this can
        only be reached through a hand-edited file (§3) -- and the engine
        must still refuse rather than quietly amortising over the shorter
        term someone wrote in."""
        data = self.build(term=3)
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2024)
        self.assertIn("müqavilə müddəti", str(e.exception))

    def test_the_rate_reported_is_1_over_the_term(self):
        info = card_of(compute_year(self.build(), 2024), "I1").rate_info
        self.assertEqual(info.method, "duz")
        self.assertEqual(info.term_years, 5)
        self.assertEqual(info.applied, D(1) / D(5))


class NotUnderArticle114(EngineTest):
    """The three fixed-asset mechanisms m.115.6-1 sits outside of."""

    def build(self, status="mikro", **kw):
        data = client(years=(2025, 2026), start_year=2025, status=status, **kw)
        data.assets = [leased_repair("I1", "5000", in_year=2025, term=5),
                       asset("A1", "ma", "1000", in_year=2025)]
        return data

    def test_the_entrepreneur_coefficient_does_not_reach_it(self):
        """m.115.6-1 has no coefficient article of its own -- unlike a QMA,
        the leased asset itself IS an əsas vəsait, but this deduction runs
        outside art. 114 altogether."""
        data = self.build()
        data.elections = [RateElection(2025, "ma", D("0.4"))]      # 20% x 2
        r = compute_year(data, 2025)
        i = card_of(r, "I1")
        self.assertEqual(i.rate_info.coefficient, D("1"))
        self.assertMoney(i.depreciation, "1000.00")
        self.assertMoney(card_of(r, "A1").depreciation, "400.00")

    def test_the_500_5_test_never_fires(self):
        data = client(years=(2025, 2026), start_year=2025)
        data.assets = [leased_repair("I1", "10000", in_year=2025, term=5)]
        data.opening_balances = [opening(2026, "I1", "400", "it")]
        r = compute_year(data, 2026)
        self.assertEqual(r.threshold_cards, [])
        self.assertEqual(r.threshold_next_cards, [])
        self.assertMoney(r.totals["writeoff"], "0.00")

    def test_a_write_off_decision_against_one_is_refused(self):
        data = self.build()
        data.writeoffs = [WriteOff(2025, "I1", "qərar")]
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2025)
        self.assertIn("114.8", str(e.exception))

    def test_a_repair_booked_against_one_is_refused(self):
        """Its own card IS the capitalised repair (m.115.6-1) -- a second
        entry in repairs.tsv would be a top-up the statute does not
        describe."""
        data = self.build()
        data.repairs = [Repair(2025, "I1", date(2025, 6, 1), D("300"))]
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2025)
        self.assertIn("115.6-1", str(e.exception))

    def test_an_election_under_a_straight_line_is_refused(self):
        data = self.build()
        data.elections = [RateElection(2025, "it", D("0.1"))]
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2025)
        self.assertIn("düz xətt", str(e.exception))


class OneCardPerRepairYear(EngineTest):
    """§10: `it` is not one card carrying several schedules -- each
    capitalised repair-year is its own independent card, exactly as
    m.115.6-1 phrases it ("hər il üzrə ayrıca olaraq kapitallaşdırılır")."""

    def test_two_repairs_on_the_same_lease_run_independently(self):
        """A 2024 repair (5000 over 5 years) and a 2026 repair (3000 over 5
        years) on the same leased shop are two cards on two clocks, not one
        pool: I1 finishes in 2028 while I2 keeps running to 2030."""
        data = client(years=tuple(range(2024, 2032)), start_year=2024)
        data.assets = [leased_repair("I1", "5000", in_year=2024, term=5),
                       leased_repair("I2", "3000", in_year=2026, term=5)]
        r2026 = compute_year(data, 2026)
        self.assertMoney(card_of(r2026, "I1").depreciation, "1000.00")
        self.assertMoney(card_of(r2026, "I2").depreciation, "600.00")
        r2029 = compute_year(data, 2029)
        self.assertTrue(card_of(r2029, "I1").retired)
        self.assertMoney(card_of(r2029, "I2").depreciation, "600.00")


class LikeAnyOtherCard(EngineTest):
    """What `it` shares with any other card (§4): acquired, carried between
    years, and folded into the same declaration line as everything else."""

    def build(self):
        data = client(years=(2025, 2026), start_year=2025)
        data.assets = [leased_repair("I1", "5000", in_year=2025, term=5),
                       asset("A1", "ma", "1000", in_year=2025)]
        return data

    def test_it_is_part_of_the_114_line(self):
        r = compute_year(self.build(), 2025)
        line = next(l for l in r.declaration if l.article == "m.114")
        self.assertMoney(line.amount, "1200.00")              # 1000 + 200

    def test_the_balance_identity_holds_with_it_in(self):
        r = compute_year(self.build(), 2026)
        lhs = (r.totals["opening"] + r.totals["acquisition"]
               + r.totals["addition"] + r.totals["repair_capitalized"]
               - r.totals["disposed"] - r.totals["depreciation"]
               - r.totals["writeoff"])
        self.assertMoney(lhs, str(r.totals["closing"]))

    def test_selling_one_still_gives_114_7_or_114_9(self):
        """Nothing in m.115.6-1 exempts a leased-repair card from disposal --
        the residual/proceeds mechanism is generic (§5.5-bis)."""
        data = self.build()
        data.disposals = [Disposal("I1", date(2026, 4, 1), "realizasiya",
                                   D("5000"))]
        r = compute_year(data, 2026)
        self.assertMoney(card_of(r, "I1").disposed, "4000.00")
        self.assertMoney(r.disposal_gain, "1000.00")


if __name__ == "__main__":
    import unittest
    unittest.main()

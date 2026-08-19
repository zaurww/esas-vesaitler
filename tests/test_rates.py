"""The rate table (§5.1) and how an asset's rate is resolved (§5.2).

These are the figures of the law and the one place where a mistake is both
easy and invisible: an over-ceiling rate is an unlawful return, and an
under-ceiling one is legal but usually not what the client meant.
"""

from decimal import Decimal
from tests.support import D, EngineTest, RateElection, asset, card_of, \
    client, owner_categories, owner_rates, rates

from engine.calc import CalcError, compute_year, rate_matrix
from engine.mutate import set_category_row


class RateTable(EngineTest):

    def test_latest_effective_year_wins(self):
        """Trucks: 5% until 2023, 8% from 2024 (1033-VIQD)."""
        self.assertEqual(rates.statutory(2023, "ym").repair_limit, D("0.05"))
        self.assertEqual(rates.statutory(2024, "ym").repair_limit, D("0.08"))
        self.assertEqual(rates.statutory(2030, "ym").repair_limit, D("0.08"))

    def test_high_tech_repair_limit_moved_in_2022(self):
        """406-VIQD put 114.3.2-1 into the 5% group."""
        self.assertEqual(rates.statutory(2021, "yt").repair_limit, D("0.03"))
        self.assertEqual(rates.statutory(2022, "yt").repair_limit, D("0.05"))

    def test_owner_row_overrides_the_shipped_default(self):
        owner_rates("effective_year\tcategory\tmax_rate\trepair_limit\tnote\n"
                    "2025\tma\t0.15\t0.04\towner\n")
        self.assertEqual(rates.statutory(2025, "ma").max_rate, D("0.15"))
        # ... and only from its own year onwards.
        self.assertEqual(rates.statutory(2024, "ma").max_rate, D("0.20"))

    def test_blank_field_in_owner_row_falls_back(self):
        """A partially filled row must not blank the field it left empty."""
        owner_rates("effective_year\tcategory\tmax_rate\trepair_limit\tnote\n"
                    "2025\tma\t\t0.04\towner\n")
        row = rates.statutory(2025, "ma")
        self.assertEqual(row.max_rate, D("0.20"))      # from the engine
        self.assertEqual(row.repair_limit, D("0.04"))  # from the owner

    def test_refresh_never_exposes_a_half_built_table(self):
        """Regression: clearing the live lists first let a concurrent reader
        fall through to the shipped default -- a silently WRONG figure (§2.1).
        Measured at 47% of reads before the fix."""
        import tempfile
        import threading
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        (tmp / "rates.tsv").write_text(
            "effective_year\tcategory\tmax_rate\trepair_limit\tnote\n"
            "2025\tym\t0.25\t0.09\towner\n", encoding="utf-8-sig")
        rates.refresh(tmp)

        seen, stop = set(), []

        def reader():
            while not stop:
                seen.add(str(rates.statutory(2026, "ym").repair_limit))

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        for _ in range(50):
            rates.refresh(tmp)
        stop.append(True)
        t.join(5)
        self.assertEqual(seen, {"0.09"})

    def test_parameter_registry(self):
        self.assertEqual(rates.parameter(2026, "threshold_abs"), D("500"))
        self.assertEqual(rates.parameter(2026, "threshold_pct"), D("0.05"))

    def test_missing_parameter_raises_rather_than_guessing(self):
        with self.assertRaises(LookupError):
            rates.parameter(2026, "no_such_parameter")

    def test_coefficient_article_number_depends_on_the_year(self):
        """297-VIIQD renumbered them; citing today's number on a 2024 report
        would send the accountant to the wrong text."""
        self.assertEqual(rates.coef_law_ref(2025, "mikro"), "VM m.114.3-1")
        self.assertEqual(rates.coef_law_ref(2026, "mikro"), "VM m.114.3-2")


class CategoryTable(EngineTest):
    """A category the code has not caught up with (§12.4-quater), read from
    `categories.tsv` and joined to the built-ins on refresh (§5.1-bis)."""

    def test_an_owner_category_joins_the_built_ins(self):
        owner_categories(
            "code\tname_az\tname_ru\tkind\tlaw_ref\tnote\n"
            "iy\tİş heyvanları\t\tev\tVM m.114.3.4\t\n"
        )
        self.assertIn("iy", rates.CATEGORY_BY_CODE)
        self.assertIn("iy", rates.EV_CODES)
        self.assertNotIn("iy", rates.QMA_CODES)
        # bt is still there -- an addition, not a replacement.
        self.assertIn("bt", rates.CATEGORY_BY_CODE)

    def test_a_category_and_its_rate_take_effect_in_one_refresh(self):
        """categories.tsv is read before rates.tsv within refresh(), so a
        rate for a brand-new code does not need a second pass to validate."""
        owner_categories(
            "code\tname_az\tname_ru\tkind\tlaw_ref\tnote\n"
            "iy\tİş heyvanları\t\tev\tVM m.114.3.4\t\n",
            rates_text="effective_year\tcategory\tmax_rate\trepair_limit\tnote\n"
                       "2024\tiy\t0.20\t\t\n",
        )
        data = client(years=(2024,))
        data.assets = [asset("A1", "iy", "1000", in_year=2024)]
        r = compute_year(data, 2024)
        self.assertMoney(card_of(r, "A1").depreciation, "200.00")

    def test_a_category_without_a_rate_fails_the_card_gracefully(self):
        """§2.1: no rate anywhere for this year must not crash has_schedule()
        with a raw LookupError -- it is CalcError, same as any other refusal
        the engine can explain."""
        owner_categories(
            "code\tname_az\tname_ru\tkind\tlaw_ref\tnote\n"
            "iy\tİş heyvanları\t\tev\tVM m.114.3.4\t\n"
        )
        data = client(years=(2024,))
        data.assets = [asset("A1", "iy", "1000", in_year=2024)]
        with self.assertRaises(CalcError) as cm:
            compute_year(data, 2024)
        self.assertIn("dərəcə təyin edilməyib", str(cm.exception))

    def test_reset_drops_owner_categories(self):
        """§11.4: EngineTest.setUp resets the rate tables between tests, so
        one test's category must not leak into the next."""
        self.assertNotIn("iy", rates.CATEGORY_BY_CODE)


class RateResolution(EngineTest):
    """§5.2: ceiling from category and status, applied rate from the most
    specific election."""

    def build(self, *, status="mikro", use_coefficient=True, elections=()):
        data = client(status=status, use_coefficient=use_coefficient)
        data.assets = [asset("A1", "nv", "10000"), asset("A2", "nv", "10000")]
        data.elections = list(elections)
        return data

    def test_coefficient_is_not_applied_on_its_own(self):
        """A right, not a duty: with no election the plain 114.3 norm applies,
        even for a micro entrepreneur entitled to double it."""
        r = compute_year(self.build(), 2024)
        cat = r.categories[0]
        self.assertEqual(cat.rate.applied, D("0.25"))    # the norm
        self.assertEqual(cat.rate.ceiling, D("0.50"))    # what was available
        self.assertFalse(cat.rate.coefficient_used)

    def test_category_election_is_used_when_present(self):
        data = self.build(elections=[RateElection(2024, "nv", D("0.50"))])
        cat = compute_year(data, 2024).categories[0]
        self.assertEqual(cat.rate.applied, D("0.50"))
        self.assertTrue(cat.rate.coefficient_used)

    def test_asset_election_beats_the_category(self):
        data = self.build(elections=[
            RateElection(2024, "nv", D("0.50")),
            RateElection(2024, "nv", D("0.10"), "A2"),
        ])
        r = compute_year(data, 2024)
        self.assertEqual(card_of(r, "A1").rate, D("0.50"))
        self.assertEqual(card_of(r, "A2").rate, D("0.10"))
        self.assertEqual(card_of(r, "A2").rate_info.source, "asset")
        self.assertTrue(r.categories[0].mixed_rates)

    def test_rate_above_the_ceiling_refuses_to_compute(self):
        """Not a warning: it would be an unlawful return (§5.2)."""
        data = self.build(status="orta",
                          elections=[RateElection(2024, "nv", D("0.30"))])
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2024)
        self.assertIn("25%", str(e.exception))

    def test_waiving_the_coefficient_lowers_the_ceiling(self):
        data = self.build(use_coefficient=False)
        cat = compute_year(data, 2024).categories[0]
        self.assertEqual(cat.rate.ceiling, D("0.25"))
        self.assertEqual(cat.rate.coefficient, D("1"))

    def test_waiver_makes_a_previously_legal_election_refuse(self):
        data = self.build(use_coefficient=False,
                          elections=[RateElection(2024, "nv", D("0.50"))])
        with self.assertRaises(CalcError):
            compute_year(data, 2024)


class RateMatrix(EngineTest):
    """§5.6-bis: the cross-year control."""

    def build(self):
        data = client(years=(2024, 2025, 2026))
        data.assets = [asset("A1", "ma", "10000", in_year=2024)]
        return data

    def test_constant_rate_is_not_flagged(self):
        mx = rate_matrix(self.build(), [2024, 2025, 2026])
        row = next(r for r in mx.rows if r.key == "ma")
        self.assertFalse(row.rate_changed)
        self.assertEqual([str(c.applied) for c in row.cells],
                         ["0.20", "0.20", "0.20"])

    def test_an_election_in_one_year_only_is_flagged(self):
        """20, 20, 18 -- legal in every single year, visible only across."""
        data = self.build()
        data.elections = [RateElection(2026, "ma", D("0.18"))]
        mx = rate_matrix(data, [2024, 2025, 2026])
        row = next(r for r in mx.rows if r.key == "ma")
        self.assertTrue(row.rate_changed)
        self.assertFalse(row.cells[1].rate_changed)
        self.assertTrue(row.cells[2].rate_changed)
        # The norm did not move -- which is the point of carrying it along.
        self.assertFalse(row.law_changed)
        self.assertEqual(row.cells[2].statutory, D("0.20"))

    def test_a_year_that_cannot_be_computed_does_not_sink_the_table(self):
        data = self.build()
        data.statuses = [s for s in data.statuses if s.year != 2025]
        mx = rate_matrix(data, [2024, 2025, 2026])
        row = next(r for r in mx.rows if r.key == "ma")
        self.assertIn(2025, mx.failed)
        self.assertFalse(row.cells[1].computed)
        self.assertTrue(row.cells[0].computed)
        self.assertTrue(row.cells[2].computed)

    def test_a_deviating_asset_gets_its_own_line(self):
        data = self.build()
        data.assets.append(asset("A2", "ma", "10000", in_year=2024))
        data.elections = [RateElection(2026, "ma", D("0.05"), "A2")]
        mx = rate_matrix(data, [2024, 2025, 2026])
        row = next(r for r in mx.rows if r.key == "ma")
        self.assertEqual([a.key for a in row.assets], ["A2"])
        self.assertTrue(row.assets[0].rate_changed)


if __name__ == "__main__":
    import unittest
    unittest.main()

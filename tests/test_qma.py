"""Qeyri-maddi aktivlər — art. 114.3.6, 118 (§5.1, §5.3).

A QMA is an ordinary card that happens to depreciate on a schedule instead of
a rate, which is why these tests care about two things above all:

  * the schedule itself -- a known term spreads the cost over its years, an
    unknown one ran at 10% of the residual until 2026 and runs over ten years
    after it (297-VIIQD of 9 Dec 2025), including for cards already on the
    books when the law moved;
  * the three fixed-asset mechanisms that must NOT reach it -- the
    entrepreneur coefficient (114.3-2/114.3-3 say "əsas vəsaitlərə"), the
    500/5% write-off (114.8 says "əsas vəsaitin"), and the art. 115 repair
    limit, which is set per category of fixed asset and has no QMA in it.

The second group is the one worth having tests for: each of those would
otherwise fail by producing a plausible number rather than an error.
"""

import dataclasses
from datetime import date

from tests.support import (
    D, Disposal, EngineTest, RateElection, Repair, WriteOff, asset, card_of,
    client, opening,
)

from engine.calc import CalcError, compute_year


def qma(aid="Q1", kind="qma-m", cost="1000", in_year=2024, life=5):
    """Bought on 1 January unless a test says otherwise: a known term runs in
    months from the month of purchase, and the tests that are about something
    else (coefficient, disposal, the 114 line) should see whole years."""
    a = asset(aid, kind, cost, in_year=in_year,
              useful_life=life if kind == "qma-m" else None)
    return dataclasses.replace(a, in_date=date(in_year, 1, 1))


class KnownTerm(EngineTest):
    """114.3.6, first half: "istifadə müddəti məlum olanlar üçün isə illər
    üzrə istifadə müddətinə mütənasib məbləğlərlə" -- the cost spread over the
    term in proportion to the use that falls in each year. Counted in MONTHS
    from the month of purchase (Category.monthly_schedule, §5.3): a one-year
    licence bought in July is used half in each of two tax years."""

    def build(self, life=5, cost="1000", month=1, day=1):
        data = client(years=tuple(range(2024, 2033)), start_year=2024)
        a = qma(cost=cost, life=life)
        data.assets = [dataclasses.replace(a, in_date=date(2024, month, day))]
        return data

    def test_bought_in_january_the_charge_is_the_same_every_year(self):
        data = self.build()
        for y in range(2024, 2029):
            self.assertMoney(card_of(compute_year(data, y), "Q1").depreciation,
                             "200.00", f"{y}")

    def test_the_year_of_acquisition_carries_only_its_months(self):
        """Bought in December: one month of sixty is used in 2024. This is
        where 114.3.6 parts from 114.4 -- a fixed asset takes the full annual
        norm whatever the month; a known-term QMA is proportional to use."""
        r = compute_year(self.build(month=12, day=20), 2024)
        self.assertMoney(card_of(r, "Q1").depreciation, "16.67")

    def test_a_one_year_licence_bought_in_july_splits_in_half(self):
        """The case that brought this in: Fortigate, 1 995 AZN, one year from
        July 2025 -- six months in each tax year."""
        data = self.build(life=1, cost="1995", month=7, day=12)
        c24 = card_of(compute_year(data, 2024), "Q1")
        c25 = card_of(compute_year(data, 2025), "Q1")
        self.assertMoney(c24.depreciation, "997.50")
        self.assertMoney(c25.depreciation, "997.50")
        self.assertMoney(c25.closing, "0.00")

    def test_the_monthly_view_covers_only_the_months_of_use(self):
        """The months are the calculation here, not just a view: the second
        half of the July licence lies in January-June, and nothing after."""
        data = self.build(life=1, cost="1995", month=7, day=12)
        m24 = card_of(compute_year(data, 2024), "Q1").monthly
        m25 = card_of(compute_year(data, 2025), "Q1").monthly
        self.assertTrue(all(v == 0 for v in m24[:6]))
        self.assertTrue(all(v > 0 for v in m24[6:]))
        self.assertTrue(all(v > 0 for v in m25[:6]))
        self.assertTrue(all(v == 0 for v in m25[6:]))
        self.assertMoney(sum(m25, D("0")), "997.50")

    def test_a_mid_year_start_runs_into_a_sixth_year_and_ends_at_zero(self):
        data = self.build(month=6, day=15)
        total = D("0")
        for y in range(2024, 2030):
            total += card_of(compute_year(data, y), "Q1").depreciation
        self.assertMoney(card_of(compute_year(data, 2024), "Q1").depreciation,
                         "116.67")                     # 7 of 60 months
        self.assertMoney(total, "1000.00")
        self.assertMoney(card_of(compute_year(data, 2029), "Q1").closing, "0.00")

    def test_and_then_the_card_stays_as_a_zero_row(self):
        c = card_of(compute_year(self.build(), 2029), "Q1")
        self.assertTrue(c.retired)
        self.assertEqual(c.retired_kind, "amortizasiya")
        self.assertMoney(c.depreciation, "0.00")

    def test_a_term_that_does_not_divide_evenly_still_ends_at_zero(self):
        """Whatever the rounding, base x used / left takes the remainder with
        it in the final share, n/n."""
        data = self.build(life=3, month=5)
        total = D("0")
        for y in range(2024, 2028):
            total += card_of(compute_year(data, y), "Q1").depreciation
        self.assertMoney(total, "1000.00")
        self.assertMoney(card_of(compute_year(data, 2027), "Q1").closing, "0.00")

    def test_a_residual_carried_in_is_spread_over_what_is_left(self):
        """Onboarding: the client's last return says 700 for a five-year asset
        bought in January 2024. 24 months are gone, 36 left, 12 of them this
        year -- not a fixed 1/5 of a cost the residual no longer matches."""
        data = self.build()
        data.opening_balances = [opening(2026, "Q1", "700", "qma-m")]
        self.assertMoney(card_of(compute_year(data, 2026), "Q1").depreciation,
                         "233.33")

    def test_the_rate_reported_is_the_norm_and_the_months_left(self):
        info = card_of(compute_year(self.build(), 2026), "Q1").rate_info
        self.assertEqual(info.method, "duz")
        self.assertEqual(info.term_years, 5)
        self.assertEqual(info.remaining_months, 36)
        self.assertEqual(info.months_this_year, 12)
        self.assertIsNone(info.remaining_years)
        self.assertEqual(info.remaining_label, "3 il")
        self.assertEqual(info.share_label, "× 12/36")
        self.assertEqual(info.applied, D(1) / D(5))

    def test_without_a_term_it_refuses_to_guess(self):
        data = self.build()
        data.assets = [asset("Q1", "qma-m", "1000", in_year=2024)]
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2024)
        self.assertIn("FİM", str(e.exception))


class UnknownTerm(EngineTest):
    """114.3.6, second half. "10 faizədək" was a norm, and a norm goes on the
    residual (114.4) -- a tail nothing ever ends, since 114.8 cannot reach a
    QMA. Law 297-VIIQD put 114.3.6 as a whole on the straight line and gave
    the unknown term a length of ten years (114.3-1.10)."""

    def build(self, in_year=2024):
        data = client(years=tuple(range(2024, 2040)), start_year=2024)
        data.assets = [qma("N1", "qma-n", "1000", in_year=in_year)]
        return data

    def test_before_2026_it_is_ten_per_cent_of_the_residual(self):
        data = self.build()
        self.assertMoney(card_of(compute_year(data, 2024), "N1").depreciation,
                         "100.00")
        self.assertMoney(card_of(compute_year(data, 2025), "N1").depreciation,
                         "90.00")
        self.assertEqual(card_of(compute_year(data, 2025), "N1").rate_info.method,
                         "azalan")

    def test_from_2026_it_is_the_residual_over_the_years_left(self):
        """810 on the books at the start of 2026, eight years of the ten still
        to run: 101.25 a year. The rule 114.11.2 states for a change of
        method, applied to the change the law itself made."""
        data = self.build()
        c = card_of(compute_year(data, 2026), "N1")
        self.assertEqual(c.rate_info.method, "duz")
        self.assertEqual(c.rate_info.term_years, 10)
        self.assertEqual(c.rate_info.remaining_years, 8)
        self.assertMoney(c.depreciation, "101.25")

    def test_and_it_reaches_zero_at_the_end_of_the_ten(self):
        data = self.build()
        self.assertMoney(card_of(compute_year(data, 2033), "N1").closing, "0.00")
        self.assertTrue(card_of(compute_year(data, 2034), "N1").retired)

    def test_one_bought_after_the_change_is_a_plain_tenth(self):
        data = self.build(in_year=2026)
        self.assertMoney(card_of(compute_year(data, 2026), "N1").depreciation,
                         "100.00")
        self.assertMoney(card_of(compute_year(data, 2030), "N1").depreciation,
                         "100.00")

    def test_one_older_than_its_term_is_finished_off(self):
        """Ten years behind it and a residual still standing: there is no
        remaining term to divide by, so what is left goes in one year rather
        than trailing forever."""
        data = client(years=(2026,), start_year=2026)
        data.assets = [asset("N1", "qma-n", "1000", in_year=2010)]
        data.opening_balances = [opening(2026, "N1", "348.68", "qma-n")]
        c = card_of(compute_year(data, 2026), "N1")
        self.assertMoney(c.depreciation, "348.68")
        self.assertMoney(c.closing, "0.00")


class NotAFixedAsset(EngineTest):
    """The three fixed-asset mechanisms a QMA is outside of. Each of them
    would otherwise produce a figure that looks perfectly reasonable."""

    def build(self, status="mikro", **kw):
        data = client(years=(2025, 2026), start_year=2025, status=status, **kw)
        data.assets = [qma("Q1", "qma-m", "1000", in_year=2025, life=5),
                       asset("A1", "ma", "1000", in_year=2025)]
        return data

    def test_the_entrepreneur_coefficient_does_not_reach_it(self):
        """114.3-2: "sahibkarlıq fəaliyyətində istifadə etdikləri ƏSAS
        VƏSAİTLƏRƏ münasibətdə". A QMA is not one (art. 118)."""
        data = self.build()
        data.elections = [RateElection(2025, "ma", D("0.4"))]     # 20% x 2
        r = compute_year(data, 2025)
        q = card_of(r, "Q1")
        self.assertEqual(q.rate_info.coefficient, D("1"))
        self.assertEqual(q.rate_info.ceiling, D(1) / D(5))
        self.assertMoney(q.depreciation, "200.00")               # not 400
        self.assertMoney(card_of(r, "A1").depreciation, "400.00")

    def test_and_no_notice_suggests_using_it_on_a_qma(self):
        r = compute_year(self.build(), 2025)
        nagging = [w for w in r.warnings if "əmsalı" in w and "QMA" in w]
        self.assertEqual(nagging, [])

    def test_the_500_5_test_never_fires(self):
        """114.8 is about "əsas vəsaitin qalıq dəyəri", and from 2026 about the
        declining balance besides. A straight line needs no cut-off: it ends
        by arriving at zero."""
        data = client(years=(2025, 2026), start_year=2025)
        data.assets = [qma("Q1", "qma-m", "2000", in_year=2025, life=5)]
        data.opening_balances = [opening(2026, "Q1", "400", "qma-m")]
        r = compute_year(data, 2026)
        self.assertEqual(r.threshold_cards, [])
        self.assertEqual(r.threshold_next_cards, [])
        self.assertMoney(r.totals["writeoff"], "0.00")

    def test_a_write_off_decision_against_one_is_refused(self):
        data = self.build()
        data.writeoffs = [WriteOff(2025, "Q1", "qərar")]
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2025)
        self.assertIn("114.8", str(e.exception))

    def test_a_repair_booked_against_one_is_refused(self):
        """The art. 115 loop walks the fixed-asset categories, so such a row
        would be stepped over and the money would vanish without a word."""
        data = self.build()
        data.repairs = [Repair(2025, "Q1", date(2025, 6, 1), D("300"))]
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2025)
        self.assertIn("115", str(e.exception))

    def test_an_election_under_a_straight_line_is_refused(self):
        """A rate below the ceiling is a choice the law offers against a norm
        on a residual. A schedule has a length, not a rate to accrue under --
        and a stored election that quietly did nothing would be worse than an
        error (§2.1)."""
        data = self.build()
        data.elections = [RateElection(2025, "qma-m", D("0.1"))]
        with self.assertRaises(CalcError) as e:
            compute_year(data, 2025)
        self.assertIn("düz xətt", str(e.exception))


class LikeAnyOtherCard(EngineTest):
    """What a QMA shares with a fixed asset, which is most of it (§4): it is
    acquired, carried between years, disposed of, and it lands in the same
    declaration line, because 118.2 deducts it as amortisation under 114."""

    def build(self):
        data = client(years=(2025, 2026), start_year=2025)
        data.assets = [qma("Q1", "qma-m", "1000", in_year=2025, life=5),
                       asset("A1", "ma", "1000", in_year=2025)]
        return data

    def test_it_is_part_of_the_114_line(self):
        r = compute_year(self.build(), 2025)
        line = next(l for l in r.declaration if l.article == "m.114")
        self.assertMoney(line.amount, "400.00")               # 200 QMA + 200 ƏV

    def test_the_balance_identity_holds_with_it_in(self):
        """§5.4.1 is checked per category inside compute_year, so reaching the
        result at all is the assertion; the totals are checked here."""
        r = compute_year(self.build(), 2026)
        lhs = (r.totals["opening"] + r.totals["acquisition"]
               + r.totals["addition"] + r.totals["repair_capitalized"]
               - r.totals["disposed"] - r.totals["depreciation"]
               - r.totals["writeoff"])
        self.assertMoney(lhs, str(r.totals["closing"]))

    def test_selling_one_gives_114_7_income(self):
        data = self.build()
        data.disposals = [Disposal("Q1", date(2026, 4, 1), "realizasiya",
                                   D("1000"))]
        r = compute_year(data, 2026)
        self.assertMoney(card_of(r, "Q1").disposed, "800.00")
        self.assertMoney(r.disposal_gain, "200.00")
        self.assertMoney(r.disposal_loss, "0.00")

    def test_and_selling_one_short_gives_114_9_loss(self):
        data = self.build()
        data.disposals = [Disposal("Q1", date(2026, 4, 1), "realizasiya",
                                   D("500"))]
        r = compute_year(data, 2026)
        self.assertMoney(r.disposal_loss, "300.00")

    def test_nothing_is_depreciated_in_the_year_it_leaves(self):
        data = self.build()
        data.disposals = [Disposal("Q1", date(2026, 4, 1), "leqv", D("0"))]
        c = card_of(compute_year(data, 2026), "Q1")
        self.assertMoney(c.depreciation, "0.00")
        self.assertMoney(c.closing, "0.00")


if __name__ == "__main__":
    import unittest
    unittest.main()

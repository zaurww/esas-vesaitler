"""The figures recorded by hand in CLAUDE.md §10, made executable.

Until now these lived as prose -- "проверено на demo-avto: 15 706,25" -- and
were re-checked by a person running `ev.py calc` and comparing with their eye.
That is a control example in the sense §5.6 asks for, but only while somebody
remembers to look. Here they run.

`demo-avto` is the client committed to the repository on purpose (see
.gitignore); the others are the owner's real data and are skipped when absent.
"""

import sys
import unittest
from decimal import Decimal

from tests.support import EngineTest, ROOT, rates

from engine.calc import compute_year
from engine.storage import load_client

DEMO = ROOT / "clients" / "demo-avto"


@unittest.skipUnless(DEMO.is_dir(), "demo-avto yoxdur")
class DemoAvto(EngineTest):
    """The whole pipeline against a real client folder: TSV parsing, the
    year chain, repairs, a disposal, the threshold and a write-off."""

    def setUp(self):
        super().setUp()
        rates.refresh(ROOT)                 # the installation's own norms
        self.data = load_client(ROOT, "demo-avto")

    def test_2025_totals(self):
        r = compute_year(self.data, 2025)
        self.assertMoney(r.totals["opening"], "54592.50")
        self.assertMoney(r.totals["acquisition"], "45000.00")
        self.assertMoney(r.totals["disposed"], "11812.50")
        self.assertMoney(r.totals["depreciation"], "15706.25")
        self.assertMoney(r.totals["writeoff"], "480.00")
        self.assertMoney(r.totals["closing"], "72877.25")

    def test_2025_repair_fund(self):
        r = compute_year(self.data, 2025)
        self.assertMoney(r.totals["repair_actual"], "2100.00")
        self.assertMoney(r.totals["repair_deductible"], "1416.50")
        self.assertMoney(r.totals["repair_capitalized"], "683.50")

    def test_2025_disposal_loss(self):
        """Sold for 9 000 against a residual of 11 812,50 (§10)."""
        r = compute_year(self.data, 2025)
        self.assertMoney(r.disposal_loss, "2812.50")
        self.assertMoney(r.disposal_gain, "0.00")

    def test_2026_totals(self):
        r = compute_year(self.data, 2026)
        self.assertMoney(r.totals["opening"], "72877.25")
        self.assertMoney(r.totals["depreciation"], "25306.12")
        self.assertMoney(r.totals["closing"], "78035.13")

    def test_the_year_chains_without_a_stored_balance(self):
        """2026 opens on exactly what 2025 closed with (§6.1)."""
        self.assertMoney(compute_year(self.data, 2026).totals["opening"],
                         f"{compute_year(self.data, 2025).totals['closing']:.2f}")

    def test_balance_identity_holds_in_both_years(self):
        for year in (2025, 2026):
            r = compute_year(self.data, year)
            for cat in r.categories:
                lhs = (cat.opening + cat.acquisition + cat.addition
                       + cat.repair_capitalized - cat.disposed
                       - cat.depreciation - cat.writeoff)
                self.assertMoney(lhs, f"{cat.closing:.2f}",
                                 f"{year} · {cat.code}")

    def test_the_threshold_spans_two_years(self):
        """NV-0005 is flagged for next year in 2025 and decidable in 2026."""
        r25 = compute_year(self.data, 2025)
        r26 = compute_year(self.data, 2026)
        self.assertIn("NV-0005", [c.inv_no for c in r25.threshold_next_cards])
        self.assertIn("NV-0005", [c.inv_no for c in r26.threshold_cards])

    def test_declaration_adds_up(self):
        r = compute_year(self.data, 2025)
        lines = {ln.article: ln.amount for ln in r.declaration}
        self.assertMoney(lines["m.114"], "15706.25")
        self.assertMoney(lines["m.115.1"], "1416.50")
        self.assertMoney(lines["m.114.8"], "480.00")
        self.assertMoney(lines["m.114.9"], "2812.50")
        self.assertMoney(r.declaration_deducted, "20415.25")

    def test_the_workbook_builds(self):
        """Not a rendering check -- just that every sheet can be produced from
        a real client without raising."""
        from engine.excel import build_workbook
        blob = build_workbook(compute_year(self.data, 2025),
                              self.data.card_meta())
        self.assertGreater(len(blob), 5000)
        self.assertEqual(blob[:2], b"PK")

    def test_rates_used_are_reported_alongside_the_figures(self):
        """§5.1: the report must be able to say where a rate came from."""
        r = compute_year(self.data, 2025)
        for cat in r.categories:
            self.assertTrue(cat.rate.statutory_year > 1900)
            self.assertLessEqual(cat.rate.applied, cat.rate.ceiling)

    def test_the_console_report_survives_an_ansi_codepage(self):
        """A Windows console starts on the ANSI codepage, where `ə ğ ı ş` do
        not exist, and `ev.py calc` used to die on UnicodeEncodeError partway
        through the first category. Başlat.bat hid it (it sets chcp 65001);
        the CLI is reached without the launcher.

        Run as a subprocess on purpose: the failure was in what the process
        does to its own streams at startup, which is not observable from
        inside this one."""
        import os
        import subprocess
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        p = subprocess.run([sys.executable, "ev.py", "calc", "demo-avto", "2025"],
                           cwd=str(ROOT), env=env, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertIn("Amortizasiya", p.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()

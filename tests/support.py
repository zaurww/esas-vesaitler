"""Shared helpers for the test suite.

Two rules the tests follow, both from CLAUDE.md:

* the engine takes events and returns a computation (§2), so most tests build
  a `ClientData` in memory -- no folder, no files, nothing to clean up;
* the rate tables are module-level state in `engine.rates` (§5.1). A test that
  writes an owner row would leak into every test after it, so `clean_rates()`
  points `refresh()` at an empty directory and every test case calls it.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import rates                                        # noqa: E402
from engine.model import (                                      # noqa: E402
    Addition, Asset, ClientData, Disposal, Group, OpeningBalance, RateElection,
    Repair, TaxpayerStatus, WriteOff,
)

D = Decimal


def clean_rates() -> None:
    """Shipped defaults only -- no owner overrides from the real installation."""
    with tempfile.TemporaryDirectory() as empty:
        rates.refresh(Path(empty))


def owner_rates(text: str) -> None:
    """Load an owner `rates.tsv` given as literal TSV text."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "rates.tsv").write_text(text, encoding="utf-8-sig")
    rates.refresh(tmp)


def owner_categories(categories_text: str, rates_text: str = "") -> None:
    """Load an owner `categories.tsv` (§5.1-bis), and optionally a matching
    `rates.tsv`, given as literal TSV text."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "categories.tsv").write_text(categories_text, encoding="utf-8-sig")
    if rates_text:
        (tmp / "rates.tsv").write_text(rates_text, encoding="utf-8-sig")
    rates.refresh(tmp)


def client(*, start_year: int = 2024, status: str = "orta",
           years: tuple[int, ...] = (2024, 2025, 2026),
           use_coefficient: bool = True, **kw) -> ClientData:
    """A client with a taxpayer status for each year and nothing else.

    `orta` by default: its coefficient is x1, so a test that is not about the
    entrepreneur coefficient does not have to think about one.
    """
    data = ClientData(slug="t", client_name="Test", voen="0",
                      start_year=start_year, format_version=1, **kw)
    data.statuses = [TaxpayerStatus(y, status, "", use_coefficient)
                     for y in years]
    return data


def asset(aid: str, category: str = "ma", cost: str = "1000",
          in_year: int | None = 2024, **kw) -> Asset:
    from datetime import date
    return Asset(asset_id=aid, inv_no=aid, name=f"Obyekt {aid}",
                 category=category,
                 in_date=date(in_year, 6, 15) if in_year else None,
                 cost=D(cost), **kw)


def opening(year: int, aid: str, residual: str, category: str = "ma",
            source: str = "onboarding") -> OpeningBalance:
    return OpeningBalance(year=year, asset_id=aid, category=category,
                          residual=D(residual), source=source)


def card_of(result, aid: str):
    return next(c for c in result.cards if c.asset_id == aid)


class EngineTest(unittest.TestCase):
    """Base case: shipped rate table, nothing carried over between tests."""

    def setUp(self) -> None:
        clean_rates()

    def assertMoney(self, got, expected: str, msg: str = "") -> None:
        self.assertEqual(f"{Decimal(got):.2f}", f"{Decimal(expected):.2f}", msg)


__all__ = [
    "D", "EngineTest", "ROOT", "Addition", "Asset", "ClientData", "Disposal",
    "Group", "OpeningBalance", "RateElection", "Repair", "TaxpayerStatus",
    "WriteOff",
    "asset", "card_of", "clean_rates", "client", "opening", "owner_categories",
    "owner_rates", "rates",
]

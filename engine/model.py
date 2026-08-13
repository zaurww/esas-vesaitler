"""Fact types (CLAUDE.md §4). Events and decisions only, never results."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

D = Decimal


@dataclass(frozen=True)
class Asset:
    """ƏV card -- the immutable acquisition fact."""
    asset_id: str
    inv_no: str
    name: str
    category: str
    in_date: Optional[date]
    cost: Decimal
    counterparty: str = ""
    useful_life: Optional[int] = None       # FİM, for category `it`
    is_legacy_pool: bool = False            # group residual carried without a card (§6.1)
    note: str = ""


@dataclass(frozen=True)
class OpeningBalance:
    """Opening balance of a year -- the only stored result (§2, §6)."""
    year: int
    asset_id: str
    category: str
    residual: Decimal
    source: str                              # onboarding | year_close
    engine_version: str = ""
    closed_at: str = ""


@dataclass(frozen=True)
class Disposal:
    asset_id: str
    date: Optional[date]
    type: str                                # realizasiya | leqv
    proceeds: Decimal = D("0")


@dataclass(frozen=True)
class Addition:
    """A capital addition to an asset already on the books.

    A component bought for an existing laptop, an extra unit bolted onto a
    machine. Unlike a repair (art. 115) it is NOT limited: it does not restore
    the asset, it enlarges it, so the whole amount joins the cost.

    The acquisition cost in assets.tsv stays the immutable original fact; the
    effective cost is derived as original + additions up to that year (§2).
    """
    year: int
    asset_id: str
    date: Optional[date]
    amount: Decimal
    note: str = ""


@dataclass(frozen=True)
class Repair:
    year: int
    asset_id: str
    date: Optional[date]
    amount: Decimal
    note: str = ""


@dataclass(frozen=True)
class TaxpayerStatus:
    """What the taxpayer IS in a given year, plus whether they take the
    coefficient that status entitles them to.

    Two different things, kept apart on purpose: the status is a fact (set by
    turnover and headcount), while waiving the coefficient is a decision.
    Folding "micro without the coefficient" into a single status value would
    throw the fact away -- the client would stop being micro in the records.
    """
    year: int
    status: str                              # mikro | kicik | orta | iri
    basis: str = ""
    use_coefficient: bool = True


@dataclass(frozen=True)
class RateElection:
    """The 114.3 rate is a ceiling; the client may accrue less (§5.2).

    An empty asset_id sets the rate for the whole category; a filled one
    overrides that single asset. Both stay capped by the same ceiling.
    """
    year: int
    category: str
    applied_rate: Decimal
    asset_id: str = ""


@dataclass(frozen=True)
class WriteOff:
    """A 500/5% write-off is the user's decision, not automatic (§5.3 step 5)."""
    year: int
    asset_id: str
    reason: str = ""


@dataclass
class ClientData:
    slug: str
    client_name: str
    voen: str
    start_year: int
    format_version: int
    assets: list[Asset] = field(default_factory=list)
    opening_balances: list[OpeningBalance] = field(default_factory=list)
    disposals: list[Disposal] = field(default_factory=list)
    repairs: list[Repair] = field(default_factory=list)
    additions: list[Addition] = field(default_factory=list)
    statuses: list[TaxpayerStatus] = field(default_factory=list)
    elections: list[RateElection] = field(default_factory=list)
    writeoffs: list[WriteOff] = field(default_factory=list)

    def status_for(self, year: int) -> Optional[TaxpayerStatus]:
        rows = [s for s in self.statuses if s.year == year]
        return rows[-1] if rows else None

    def election_for(self, year: int, category: str,
                     asset_id: str = "") -> Optional[RateElection]:
        """Most specific election wins: the asset's own, then the category's."""
        if asset_id:
            rows = [e for e in self.elections
                    if e.year == year and e.asset_id == asset_id]
            if rows:
                return rows[-1]
        rows = [e for e in self.elections
                if e.year == year and e.category == category and not e.asset_id]
        return rows[-1] if rows else None

    def closed_years(self) -> set[int]:
        """Year N is closed once an opening balance for N+1 exists with source=year_close."""
        return {
            ob.year - 1
            for ob in self.opening_balances
            if ob.source == "year_close"
        }

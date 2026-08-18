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
    # Identifiers the tax calculation never touches, kept because the card is
    # also the place an accountant comes to ANSWER things: which e-invoice this
    # was bought on, which physical unit of forty identical ones this is. Both
    # optional -- plenty of clients keep neither, and a blank column is not a
    # missing fact.
    e_qaime: str = ""                       # e-qaimə (electronic invoice) no.
    serial_no: str = ""                     # serial / VIN / factory number
    # The client's own classification, beside the tax one and never instead of
    # it: laptops, servers and printers are all `yt` at one rate, and the
    # office still wants them apart. A reference into groups.tsv, never a
    # name: the name is renameable, so storing it on the card would mean
    # editing forty cards to fix one spelling (§4, the inv_no reasoning).
    #
    # It reaches NO calculation. That is the whole constraint: the moment a
    # group carries a rate or a repair limit of its own it becomes a
    # substitute category, and the aggregation by art. 114/115 stops being
    # universal (§13.1).
    group_id: str = ""
    useful_life: Optional[int] = None       # FİM, for category `it`
    is_legacy_pool: bool = False            # group residual carried without a card (§6.1)
    note: str = ""


@dataclass(frozen=True)
class Group:
    """A client's own grouping inside a tax category (§13.1).

    A dictionary row rather than free text on the card, for the same reason
    `category` is an enum: "Serverlər" and "Serverler" typed on two different
    days would silently become two groups, and a report split in two is worse
    than no report (§2.1). Renaming one is one edit here, not forty there.
    """
    group_id: str
    name: str
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
    groups: list[Group] = field(default_factory=list)

    def group_name(self, group_id: str) -> str:
        return next((g.name for g in self.groups if g.group_id == group_id), "")

    def card_meta(self) -> dict[str, dict[str, str]]:
        """Card fields the calculation never reads, keyed by asset_id.

        The client's group is here for exactly that reason: it is reporting,
        not tax. `CardResult` has no group and must not grow one.

        `CardResult` deliberately carries only what the pipeline works on, so
        the counterparty, the e-invoice and the serial have to travel beside
        it. One lookup for all of them: they are the same kind of thing --
        what the card says about itself -- and a separate dict per field meant
        a new field touched every caller.
        """
        names = {g.group_id: g.name for g in self.groups}
        return {a.asset_id: {"counterparty": a.counterparty,
                             "e_qaime": a.e_qaime,
                             "serial_no": a.serial_no,
                             "group_id": a.group_id,
                             # The name travels with the id because every
                             # reader of this dict is about to display it, and
                             # resolving it at each one is how a stale name
                             # gets printed somewhere.
                             "group": names.get(a.group_id, "")}
                for a in self.assets}

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
        """Locked years: their facts are frozen because the return was filed.

        Locking is a deliberate act and is now independent of how balances
        move between years -- those carry forward on their own (§6). A lock
        also stores a snapshot, which is what `ev.py verify` checks against.
        """
        return {
            ob.year - 1
            for ob in self.opening_balances
            if ob.source == "year_close"
        }

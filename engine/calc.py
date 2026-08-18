"""The year pipeline (CLAUDE.md §5.3). Stateless: events in, computation out.

    1. opening_residual
    2. + acquisitions          bought this year, FULL annual rate, no proration
    3. + capitalized_repair    art. 115 excess over the group limit
    4. - disposed_residual     residual of assets that left
       = base
    5. threshold_test          against step 1, BEFORE any depreciation
    6. x applied_rate          depreciation for the year
    7. = closing_residual

Step 6 has two forms, and which one applies is a fact about the year, not
about the asset (§5.1, RateRow.method):

    azalan   base x rate             declining balance, art. 114.4
    duz      base / remaining term   straight line, art. 114.3.6 for QMA

Everything around step 6 is shared, which is why a QMA is an ordinary card in
assets.tsv and not a parallel world: it is acquired, carried, disposed of and
sealed exactly like a fixed asset (§4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from . import rates
from .model import ClientData
from .rates import (
    CATEGORIES, CATEGORY_BY_CODE, ENGINE_VERSION, EV_CODES, FORMAT_VERSION,
    QMA_CODES, STATUS_NAMES, multiplier, statutory,
)

D = Decimal
ZERO = D("0")
CENT = D("0.01")


class CalcError(Exception):
    """The calculation did not complete. Never replaced by a zero (§2.1)."""


def money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class CardResult:
    asset_id: str
    inv_no: str
    name: str
    category: str
    in_date: Optional[date]
    cost: Decimal
    is_legacy_pool: bool

    opening: Decimal = ZERO
    acquisition: Decimal = ZERO
    addition: Decimal = ZERO          # capitalised component bought this year
    cost_prior: Decimal = ZERO        # original cost + additions of past years
    repair_actual: Decimal = ZERO
    repair_deductible: Decimal = ZERO
    repair_capitalized: Decimal = ZERO
    disposed: Decimal = ZERO
    base: Decimal = ZERO
    rate: Decimal = ZERO
    depreciation: Decimal = ZERO
    writeoff: Decimal = ZERO
    closing: Decimal = ZERO

    opening_source: str = "none"      # explicit | carried | none
    threshold_hit: bool = False       # opening residual trips it -> this year
    threshold_reason: str = ""
    threshold_next: bool = False      # closing residual trips it -> next year
    threshold_next_reason: str = ""
    written_off: bool = False

    # -- assets whose life is over -----------------------------------------
    # Zero in every column, present in every list. The report used to drop a
    # card the year after its residual reached zero, on the reasoning that it
    # is no longer on the balance sheet -- true, and beside the point: the
    # accountant still has the physical thing, still gets asked what happened
    # to it, and "it vanished from the report" is not an answer. So the row
    # stays, carrying nothing, saying how it ended.
    #
    # Nothing here can move a total: every figure on a retired card is zero,
    # and the balance identity (§5.4.1) adds zeros on both sides.
    retired: bool = False
    retired_kind: str = ""    # writeoff | realizasiya | leqv | amortizasiya
    retired_year: Optional[int] = None

    disposal_type: str = ""
    disposal_date: Optional[date] = None
    proceeds: Decimal = ZERO
    gain_loss: Decimal = ZERO
    rate_info: Optional["RateInfo"] = None

    monthly: list[Decimal] = field(default_factory=list)

    # -- gross cost and accumulated depreciation ---------------------------
    # The tax pipeline only needs the residual, but the movement statement an
    # accountant hands over wants both halves: cost moving on one side,
    # accumulated depreciation on the other, meeting at the residual.
    #
    # When the initial cost is unknown (a legacy pool, or an asset carried in
    # with only a residual), the residual IS the carrying amount: gross starts
    # equal to it and accumulated starts at zero. Inventing a cost would be
    # inventing history.

    @property
    def cost_effective(self) -> Decimal:
        """Original cost plus everything capitalised onto it so far."""
        return self.cost_prior + self.addition + self.repair_capitalized

    @property
    def gross_start(self) -> Decimal:
        if self.acquisition > ZERO and self.opening == ZERO:
            return ZERO                       # acquired during the year
        return self.cost_prior if self.cost_prior > ZERO else self.opening

    @property
    def gross_in(self) -> Decimal:
        acq = self.acquisition if self.opening == ZERO else ZERO
        return acq + self.addition + self.repair_capitalized

    @property
    def gross_out(self) -> Decimal:
        return self.gross_start + self.gross_in if self.disposal_type else ZERO

    @property
    def gross_end(self) -> Decimal:
        return self.gross_start + self.gross_in - self.gross_out

    @property
    def accumulated_start(self) -> Decimal:
        return self.gross_start - self.opening

    @property
    def accumulated_out(self) -> Decimal:
        return self.gross_out - self.disposed if self.disposal_type else ZERO

    @property
    def accumulated_end(self) -> Decimal:
        return (self.accumulated_start + self.depreciation + self.writeoff
                - self.accumulated_out)


@dataclass
class RateInfo:
    category: str
    statutory_max: Decimal
    statutory_year: int
    status: str
    coefficient: Decimal
    ceiling: Decimal
    applied: Decimal
    elected: bool
    below_ceiling: bool
    below_statutory: bool = False     # deliberately under the plain 114.3 norm
    coefficient_used: bool = False    # the entrepreneur right is being exercised
    source: str = "norm"              # asset | category | norm

    # -- straight line -----------------------------------------------------
    # `applied` is still the norm (1/term), because that is the figure that
    # stays put year after year and therefore the one the rate matrix can
    # compare (§5.6-bis). It is NOT the fraction of this year's base: the
    # charge is base / remaining, so a report that prints a bare percentage
    # next to the base would invite a multiplication that does not reproduce
    # the number. Whoever prints these prints the term and what is left of it.
    method: str = "azalan"            # azalan | duz
    term_years: Optional[int] = None
    remaining_years: Optional[int] = None
    per_card: bool = False            # the term lives on the card, not here


@dataclass
class CategoryResult:
    code: str
    name_az: str
    name_ru: str
    rate: RateInfo                    # the category default
    cards: list[CardResult] = field(default_factory=list)
    mixed_rates: bool = False         # at least one asset overrides it

    opening: Decimal = ZERO
    acquisition: Decimal = ZERO
    addition: Decimal = ZERO
    repair_actual: Decimal = ZERO
    repair_limit: Decimal = ZERO
    repair_limit_pct: Decimal = ZERO
    repair_deductible: Decimal = ZERO
    repair_capitalized: Decimal = ZERO
    disposed: Decimal = ZERO
    depreciation: Decimal = ZERO
    writeoff: Decimal = ZERO
    closing: Decimal = ZERO
    monthly: list[Decimal] = field(default_factory=list)


@dataclass(frozen=True)
class DeclarationLine:
    """One figure this program hands to the profit-tax return.

    Everything else the engine produces is working material -- the movement of
    a card, the base of a category, the split by month. These five figures are
    the output proper: they are what gets copied into the return, and the whole
    calculation exists to arrive at them.

    They used to have no single place. Depreciation sat in the headline tiles,
    the repair deduction on its own tab, the 114.8 write-off in a tile named
    after the test rather than after what it does, and 114.7/114.9 among the
    warnings. Every number was on screen and the answer to "what do I put in
    the return" was still assembled by hand from four screens.

    Named once, here, because three outputs print it -- console, web report,
    workbook. A list restated in each would drift the way the norm-file list
    did before it became rates.NORM_FILES (§5.1).
    """
    article: str
    label_az: str
    amount: Decimal
    effect: str                       # deduction | income

    @property
    def signed(self) -> Decimal:
        """Effect on taxable profit: income raises it, a deduction lowers it."""
        return self.amount if self.effect == "income" else -self.amount


@dataclass
class YearResult:
    client_name: str
    voen: str
    slug: str
    start_year: int
    year: int
    is_closed: bool
    status: str
    status_name: str
    use_coefficient: bool
    engine_version: str
    format_version: int
    carried_from_prev: bool = False   # opening balances chained from year-1
    categories: list[CategoryResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    totals: dict[str, Decimal] = field(default_factory=dict)
    monthly: list[Decimal] = field(default_factory=list)

    # Art. 114.7 / 114.9: the difference between what an asset sold for and
    # what it was still worth on the books. NOT part of depreciation -- these
    # are their own lines in the profit return, one adding to income, the
    # other deducting from it, so they are kept apart from the totals above.
    disposal_gain: Decimal = ZERO     # 114.7 -- added to income
    disposal_loss: Decimal = ZERO     # 114.9 -- deducted from income

    @property
    def disposed_cards(self) -> list[CardResult]:
        return [c for c in self.cards if c.disposal_type]

    @property
    def cards(self) -> list[CardResult]:
        return [c for cat in self.categories for c in cat.cards]

    @property
    def threshold_cards(self) -> list[CardResult]:
        return [c for c in self.cards if c.threshold_hit]

    @property
    def threshold_next_cards(self) -> list[CardResult]:
        return [c for c in self.cards if c.threshold_next]

    # -- what goes into the return -----------------------------------------
    # Derived, never stored (§2). The order is the order of the pipeline that
    # produced them, not the order of the form: depreciation, then repair,
    # then the two things that happen when an asset leaves.

    @property
    def declaration(self) -> list[DeclarationLine]:
        t = self.totals
        z = lambda k: t.get(k, ZERO)                            # noqa: E731
        return [
            DeclarationLine("m.114", "Amortizasiya ayırmaları",
                            z("depreciation"), "deduction"),
            DeclarationLine("m.115.1", "Təmir xərcləri — hədd daxilində",
                            z("repair_deductible"), "deduction"),
            DeclarationLine("m.114.8",
                            f"Birdəfəlik silinmə ({threshold_label(self.year)})",
                            z("writeoff"), "deduction"),
            DeclarationLine("m.114.9", "Təqdim edilmədən zərər",
                            self.disposal_loss, "deduction"),
            DeclarationLine("m.114.7", "Təqdim edilmədən gəlir",
                            self.disposal_gain, "income"),
        ]

    @property
    def declaration_deducted(self) -> Decimal:
        return sum((l.amount for l in self.declaration
                    if l.effect == "deduction"), ZERO)

    @property
    def declaration_income(self) -> Decimal:
        return sum((l.amount for l in self.declaration
                    if l.effect == "income"), ZERO)

    @property
    def declaration_net(self) -> Decimal:
        """Net effect on taxable profit. Negative in almost every year: this
        program's job is mostly to find deductions."""
        return self.declaration_income - self.declaration_deducted


MONTHS_AZ = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "İyun",
             "İyul", "Avqust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]


def split_monthly(annual: Decimal) -> list[Decimal]:
    """Annual amount / 12, rounding remainder pushed into December so the
    twelve parts add back up to the annual figure exactly.

    The monthly split is a VIEW, not a separate calculation: the legally
    binding number is the annual one (the return is filed once a year, §6).
    """
    if annual == ZERO:
        return [ZERO] * 12
    per = money(annual / D(12))
    out = [per] * 11
    out.append(money(annual - per * 11))
    return out


def threshold_test(card: "CardResult", residual: Decimal, year: int,
                   cost_at: Decimal | None = None) -> tuple[bool, str]:
    """The one-off write-off test of art. 114.8, as it stood in `year`.

    Both figures come from the parameter table rather than from constants, so
    an amendment to 114.8 is a row someone types, not a new release of this
    program. `year` matters for the same reason it matters for a rate: the
    test that applies is the one in force for the year being computed.

    A legacy pool row carries no initial cost of its own, so only the flat
    money half of the test applies to it (§6.1).
    """
    if residual <= ZERO:
        return False, ""
    abs_limit = rates.parameter(year, "threshold_abs")
    pct_limit = rates.parameter(year, "threshold_pct")
    reasons = []
    if residual < abs_limit:
        reasons.append(f"qalıq {residual:.2f} < {abs_limit:g} AZN")
    # Measured against the cost INCLUDING capitalised additions: a laptop
    # that got a component is a more expensive asset than it was.
    base_cost = cost_at if cost_at is not None else card.cost_effective
    if not card.is_legacy_pool and base_cost > ZERO \
            and residual < base_cost * pct_limit:
        reasons.append(
            f"qalıq {residual:.2f} < ilkin dəyərin {pct_limit:.0%}-i "
            f"({money(base_cost * pct_limit)} AZN)"
        )
    return bool(reasons), "; ".join(reasons)


def threshold_label(year: int) -> str:
    """How the test is named in messages -- "500/5%" is only today's wording."""
    return (f"{rates.parameter(year, 'threshold_abs'):g}/"
            f"{rates.parameter(year, 'threshold_pct'):.0%}")


def compute_year(data: ClientData, year: int,
                 _cache: dict | None = None, _depth: int = 0) -> YearResult:
    """Compute one year.

    Opening balances resolve PER ASSET, most specific first:

        1. an explicit row in opening_balances.tsv for (year, asset)
           -- onboarding, a correction, or a snapshot written by a lock;
        2. otherwise the asset's closing balance from the previous year,
           computed by running that year too;
        3. otherwise zero.

    Rule 2 is why a client whose data starts in 2024 can be entered as 2024,
    then 2025, then 2026 without any ceremony in between. Carrying balances
    forward is arithmetic, not an act -- §2 says results are computed. What
    IS an act is locking a year, and that is now a separate thing (§6).
    """
    if _cache is None:
        _cache = {}
    if year in _cache:
        return _cache[year]
    status_row = data.status_for(year)
    if status_row is None:
        raise CalcError(
            f"taxpayer_status.tsv-də {year} ili üçün sətir yoxdur — "
            f"sahibkarlıq statusu olmadan normaya tətbiq olunan əmsal məlum deyil"
        )

    mult = multiplier(year, status_row.status)
    if not status_row.use_coefficient:
        # The right is waived for the year: the ceiling drops to the plain
        # article 114.3 norm and the report stops suggesting the coefficient.
        mult = mult._replace(coefficient=D("1"))
    result = YearResult(
        client_name=data.client_name,
        voen=data.voen,
        slug=data.slug,
        start_year=data.start_year,
        year=year,
        is_closed=year in data.closed_years(),
        status=status_row.status,
        status_name=STATUS_NAMES[status_row.status]
        + ("" if status_row.use_coefficient else " · əmsalsız"),
        use_coefficient=status_row.use_coefficient,
        engine_version=ENGINE_VERSION,
        format_version=data.format_version,
    )

    assets = {a.asset_id: a for a in data.assets}
    explicit = {ob.asset_id: ob.residual
                for ob in data.opening_balances if ob.year == year}

    # Chain back to the previous year for anything not stated explicitly.
    # _depth guards against a corrupt start_year sending this into a loop.
    carried: dict[str, Decimal] = {}
    prev_ok = False
    if (year > data.start_year and _depth < 40
            and data.status_for(year - 1) is not None):
        prev = compute_year(data, year - 1, _cache, _depth + 1)
        prev_ok = True
        for c in prev.cards:
            if c.closing > ZERO:
                carried[c.asset_id] = c.closing
    disposals = {d.asset_id: d for d in data.disposals
                 if d.date is not None and d.date.year == year}
    writeoffs = {w.asset_id for w in data.writeoffs if w.year == year}
    repairs: dict[str, Decimal] = {}
    for r in data.repairs:
        if r.year == year:
            repairs[r.asset_id] = repairs.get(r.asset_id, ZERO) + r.amount
    # Art. 115 sets its limit per CATEGORY OF FIXED ASSET; a QMA belongs to
    # none of them, so the repair loop below (EV_CODES) would step straight
    # over such a row and the money would disappear without a word -- the one
    # failure §2.1 rules out. Refused here instead, where the row can be named.
    for aid in repairs:
        a = assets.get(aid)
        if a is not None and CATEGORY_BY_CODE[a.category].kind == "qma":
            raise CalcError(
                f"{a.inv_no or aid}: qeyri-maddi aktiv üçün təmir xərci "
                f"yazılıb ({year}), lakin m.115 təmir həddi yalnız əsas "
                f"vəsait kateqoriyaları üçün müəyyən edilir. "
                f"repairs.tsv-dəki sətri silin."
            )
    additions: dict[str, Decimal] = {}
    additions_prior: dict[str, Decimal] = {}
    for a in data.additions:
        if a.year == year:
            additions[a.asset_id] = additions.get(a.asset_id, ZERO) + a.amount
        elif a.year < year:
            additions_prior[a.asset_id] = \
                additions_prior.get(a.asset_id, ZERO) + a.amount

    # -- rate resolution ----------------------------------------------------
    # The entrepreneur coefficient raises the CEILING; it is a right, not a
    # duty, so it is never applied on its own. With no election the plain
    # article 114.3 norm applies -- the engine must not decide to double a
    # client's depreciation for them.
    # The most specific election wins: the asset's own, then the category's.
    def straight_term(code: str, asset) -> Optional[int]:
        """How many years a straight-line schedule runs for.

        `qma-m` reads it off the card -- that is what "istifadə müddəti məlum"
        means, and it is why the FİM is required there. `qma-n` reads it from
        the parameter table, because for an unknown term the law supplies the
        length itself (114.3-1.10: ten years).

        None means the category has no single term to state -- the term is per
        card, so the category header cannot print one.
        """
        if code == "qma-m":
            if asset is None:
                return None
            life = asset.useful_life
            if not life or life < 1:
                raise CalcError(
                    f"{asset.inv_no or asset.asset_id}: istifadə müddəti (FİM) "
                    f"göstərilməyib — m.114.3.6 üzrə düz xətt metodu müddət "
                    f"olmadan hesablana bilmir. Kartı redaktə edib FİM yazın."
                )
            return int(life)
        if code == "qma-n":
            return int(rates.parameter(year, "qma_term_unknown"))
        raise CalcError(
            f"{code}: düz xətt metodu üçün müddət mənbəyi müəyyən edilməyib"
        )

    def resolve_rate(code: str, asset_id: str = "", asset=None) -> RateInfo:
        st = statutory(year, code)
        # 114.3-2 and 114.3-3 grant the coefficient "əsas vəsaitlərə
        # münasibətdə" -- with respect to FIXED assets. A QMA is not one
        # (art. 118), so its ceiling is the plain norm and the taxpayer's
        # status moves nothing.
        is_qma = CATEGORY_BY_CODE[code].kind == "qma"
        coefficient = D("1") if is_qma else mult.coefficient
        election = data.election_for(year, code, asset_id)

        if st.method == "duz":
            # No election under a straight line. "10 faizədək" was a ceiling
            # while the norm ran against a residual; once the law fixes a
            # SCHEDULE ("mütənasib məbləğlərlə", plus a term in 114.3-1.10),
            # there is no lower rate to choose -- there is a length. A stored
            # election is refused rather than ignored (§2.1): it would
            # otherwise sit in the file looking as though it applied.
            if election is not None:
                raise CalcError(
                    f"{code}: düz xətt metodu ilə hesablanır — dərəcə seçimi "
                    f"tətbiq olunmur ({year} il). rate_elections.tsv-dəki sətri "
                    f"silin; müddət kartdakı FİM ilə müəyyən edilir."
                )
            term = straight_term(code, asset)
            if term is None:
                # Category level: every card has its own term, so there is no
                # single norm to state. Said explicitly rather than printed as
                # zero per cent, which would read as "nothing is accrued".
                return RateInfo(
                    category=code, statutory_max=ZERO,
                    statutory_year=st.effective_year, status=status_row.status,
                    coefficient=coefficient, ceiling=ZERO, applied=ZERO,
                    elected=False, below_ceiling=False,
                    method="duz", per_card=True,
                )
            norm = D(1) / D(term)
            remaining = None
            if asset is not None:
                if asset.in_date is None:
                    raise CalcError(
                        f"{asset.inv_no or asset.asset_id}: alış tarixi yoxdur "
                        f"— düz xətt metodu üçün cədvəlin başlanğıcı məlum "
                        f"olmalıdır."
                    )
                # Years already behind it. The year of acquisition is year
                # zero: a full annual amount is charged in it, exactly as for
                # a fixed asset (§5.3 step 2) -- neither 114.3.6 nor 114.6
                # knows anything about months.
                remaining = max(1, term - (year - asset.in_date.year))
            return RateInfo(
                category=code, statutory_max=norm,
                statutory_year=st.effective_year, status=status_row.status,
                coefficient=coefficient, ceiling=norm, applied=norm,
                elected=False, below_ceiling=False,
                method="duz", term_years=term, remaining_years=remaining,
            )

        if st.max_rate is None:
            raise CalcError(
                f"{code}: dərəcə istifadə müddətindən (FİM) çıxarılır — mərhələ 1b"
            )
        ceiling = min(st.max_rate * coefficient, D("1"))
        applied = election.applied_rate if election else st.max_rate
        if applied > ceiling:
            where = f"{election.asset_id}: " if election and election.asset_id else ""
            raise CalcError(
                f"{code}: {where}seçilmiş dərəcə {applied:%} yuxarı həddi "
                f"{ceiling:%} aşır ({st.max_rate:%} × {coefficient}, {year} il). "
                f"Hesablama dayandırıldı — bu, qanunsuz bəyannaməyə gətirib çıxarardı."
            )
        if applied < ZERO:
            raise CalcError(f"{code}: dərəcə mənfidir — {applied}")
        return RateInfo(
            category=code, statutory_max=st.max_rate, statutory_year=st.effective_year,
            status=status_row.status, coefficient=coefficient, ceiling=ceiling,
            applied=applied, elected=election is not None,
            below_ceiling=applied < ceiling,
            below_statutory=applied < st.max_rate,
            coefficient_used=applied > st.max_rate,
            source=("asset" if election and election.asset_id
                    else "category" if election else "norm"),
            method=st.method,
        )

    # A category can be computed once its schedule has a source: a rate for
    # the declining balance, a term for the straight line. `it` has neither
    # yet (its term is the lease contract, §12.5), and says so per card below
    # rather than by disappearing from the report.
    def has_schedule(code: str) -> bool:
        st = statutory(year, code)
        return st.method == "duz" or st.max_rate is not None

    priceable = {c.code for c in CATEGORIES if has_schedule(c.code)}

    # An asset counts as having STARTED once it was bought, or once a balance
    # was recorded for it, in this year or any earlier one. The distinction
    # matters below: nothing on the books and never started is an asset that
    # does not exist yet; nothing on the books after it started is an asset
    # whose life is over.
    started: set[str] = {
        aid for aid, a in assets.items()
        if a.in_date is not None and a.in_date.year <= year
    }
    started |= {ob.asset_id for ob in data.opening_balances if ob.year <= year}

    # Retirements, whenever they happened -- the reason a spent card is spent.
    disposed_ever = {d.asset_id: d for d in data.disposals if d.date is not None}
    written_ever: dict[str, int] = {}
    for w in data.writeoffs:
        if w.asset_id not in written_ever or w.year < written_ever[w.asset_id]:
            written_ever[w.asset_id] = w.year

    # -- step 1: opening balances and acquisitions --------------------------
    cards: dict[str, CardResult] = {}
    for aid, asset in assets.items():
        if CATEGORY_BY_CODE[asset.category].kind not in ("ev", "qma"):
            continue
        if aid in explicit:
            open_val, open_src = explicit[aid], "explicit"
        elif aid in carried:
            open_val, open_src = carried[aid], "carried"
        else:
            open_val, open_src = ZERO, "none"
        acq = ZERO
        if asset.in_date is not None and asset.in_date.year == year:
            acq = asset.cost
        retired = False
        if open_val == ZERO and acq == ZERO:
            # Nothing carried in and nothing bought. Three different things,
            # and they used to be one `continue`:
            if additions.get(aid, ZERO) or repairs.get(aid, ZERO):
                pass          # spent, but money was put into it this year --
                              # it comes back onto the books and must be
                              # computed, not dropped in silence (§2.1)
            elif aid in started:
                retired = True   # its life is over; kept as a zero row so the
                                 # list still shows it (see CardResult.retired)
            else:
                continue      # not bought yet -- it does not exist in this year
        cards[aid] = CardResult(
            asset_id=aid, inv_no=asset.inv_no, name=asset.name,
            category=asset.category, in_date=asset.in_date, cost=asset.cost,
            is_legacy_pool=asset.is_legacy_pool,
            opening=open_val,
            opening_source=open_src,
            acquisition=acq,
            addition=additions.get(aid, ZERO),
            cost_prior=asset.cost + additions_prior.get(aid, ZERO),
            retired=retired,
        )
        if retired:
            c = cards[aid]
            if aid in written_ever and written_ever[aid] < year:
                c.retired_kind, c.retired_year = "writeoff", written_ever[aid]
            elif aid in disposed_ever and disposed_ever[aid].date.year < year:
                c.retired_kind = ("realizasiya"
                                  if disposed_ever[aid].type == "realizasiya"
                                  else "leqv")
                c.retired_year = disposed_ever[aid].date.year
            else:
                c.retired_kind = "amortizasiya"

    # -- step 3: art. 115 repairs (limit per group, spend recorded per asset)
    for code in EV_CODES:
        group = [c for c in cards.values() if c.category == code]
        group_repairs = {c.asset_id: repairs.get(c.asset_id, ZERO) for c in group}
        actual_total = sum(group_repairs.values(), ZERO)
        if actual_total == ZERO:
            continue
        st = statutory(year, code)
        if st.repair_limit is None:
            continue
        opening_total = sum((c.opening for c in group), ZERO)
        limit = money(opening_total * st.repair_limit)
        # The deductible total is fixed by law: MIN(limit, actual). Split it
        # across the assets pro rata to their own repair spend, rounding to
        # the qəpik and giving the last one the remainder, so the parts add
        # back up to that total exactly (§5.3 rounding rule).
        deductible_total = min(limit, actual_total)
        spenders = [c for c in group if group_repairs[c.asset_id] != ZERO]
        allocated = ZERO
        for i, c in enumerate(spenders):
            amt = group_repairs[c.asset_id]
            if i == len(spenders) - 1:
                share = deductible_total - allocated
            else:
                share = money(deductible_total * amt / actual_total)
                allocated += share
            c.repair_actual = amt
            c.repair_deductible = share
            c.repair_capitalized = amt - share

    # -- steps 4-7, per card ------------------------------------------------
    for c in cards.values():
        if c.category not in priceable:
            raise CalcError(
                f"{c.inv_no or c.asset_id}: {c.category} kateqoriyası hələ "
                f"dəstəklənmir (dərəcə istifadə müddətindən, mərhələ 1b)"
            )
        c.rate_info = resolve_rate(c.category, c.asset_id, assets[c.asset_id])
        if c.retired:
            # Nothing to depreciate and therefore no rate to state. Leaving
            # the category rate on the row printed "20%" next to a line of
            # dashes, which invites the reader to look for the 20% of nothing.
            c.rate = ZERO
            c.monthly = [ZERO] * 12
            continue
        disp = disposals.get(c.asset_id)
        if disp is not None:
            c.disposal_type = disp.type
            c.disposal_date = disp.date
            c.proceeds = disp.proceeds
            c.disposed = (c.opening + c.acquisition + c.addition
                          + c.repair_capitalized)
            c.gain_loss = disp.proceeds - c.disposed
            c.base = ZERO
            c.closing = ZERO
            c.monthly = [ZERO] * 12
            continue

        c.base = (c.opening + c.acquisition + c.addition
                  + c.repair_capitalized)

        # step 5: the write-off test runs on the pre-depreciation residual,
        # measured against the asset's initial cost.
        #
        # Not for a QMA: 114.8 speaks of "əsas vəsaitin qalıq dəyəri", and
        # from 2026 it opens with "azalan qalıq dəyəri metodu ilə amortizasiya
        # hesablanması zamanı" -- twice out of reach of an intangible. A
        # straight line needs no such cut-off anyway: it ends by arriving at
        # zero, which is what the declining balance never does.
        if CATEGORY_BY_CODE[c.category].kind == "ev":
            c.threshold_hit, c.threshold_reason = threshold_test(
                c, c.opening, year,
                c.cost_prior)               # start of year: before this year's
                                            # additions existed

        if (c.asset_id in writeoffs
                and CATEGORY_BY_CODE[c.category].kind == "qma"):
            raise CalcError(
                f"{c.inv_no or c.asset_id}: qeyri-maddi aktiv üçün m.114.8 "
                f"silinmə qərarı yazılıb ({year}), lakin bu hədd yalnız əsas "
                f"vəsaitlərə aiddir. writeoffs.tsv-dəki sətri silin."
            )
        if c.threshold_hit and c.asset_id in writeoffs:
            c.written_off = True
            c.writeoff = money(c.base)
            c.depreciation = ZERO
            c.closing = ZERO
        else:
            info = c.rate_info
            c.rate = info.applied
            if info.method == "duz":
                # base / what is left of the term, not cost x norm. The two
                # agree for an asset that started here and was left alone, and
                # they must NOT agree otherwise: a residual carried in from
                # the client's last return, or one left standing when 2026
                # moved `qma-n` off the declining balance, is exactly where a
                # fixed 1/term leaves a stub or overshoots. Dividing what is
                # on the books by the years it has left arrives at zero at the
                # end of the term either way -- the rule 114.11.2 states for a
                # change of method, applied to the same situation.
                c.depreciation = money(c.base / D(info.remaining_years))
            else:
                c.depreciation = money(c.base * info.applied)
            if c.depreciation > c.base:
                c.depreciation = money(c.base)
            c.closing = money(c.base - c.depreciation)
        c.monthly = split_monthly(c.depreciation)

        # Same test against the closing residual. That residual becomes next
        # year's opening balance, so this is a reliable forecast of which
        # assets will fall under the threshold in the year ahead. It does NOT
        # write anything off now -- see CLAUDE.md §12.6.
        #
        # Tested with NEXT year's figures, because that is the year the
        # write-off would happen. With the threshold hardcoded this could not
        # go wrong; now that an amendment can move it, forecasting a 2027
        # write-off against the 2026 threshold would be simply wrong.
        if not c.written_off and CATEGORY_BY_CODE[c.category].kind == "ev":
            c.threshold_next, c.threshold_next_reason = threshold_test(
                c, c.closing, year + 1)

    # -- roll the cards up into categories ----------------------------------
    # QMA categories sit in the same list as the fixed ones, on purpose: art.
    # 118.2 deducts them as amortisation computed under art. 114, so they are
    # part of the same declaration line and must be part of the same total.
    for code in EV_CODES + QMA_CODES:
        group = sorted(
            (c for c in cards.values() if c.category == code),
            # Spent cards sink to the bottom of their group: they are there to
            # be found, not to be read past on the way to the live ones.
            key=lambda c: (c.retired, not c.is_legacy_pool, c.inv_no, c.name),
        )
        if not group or code not in priceable:
            continue
        cat_rate = resolve_rate(code)         # the category default
        cat = CategoryResult(
            code=code,
            name_az=CATEGORY_BY_CODE[code].name_az,
            name_ru=CATEGORY_BY_CODE[code].name_ru,
            rate=cat_rate,
            cards=group,
            # Measured against the category rate, not just card against card.
            # Comparing the cards only to each other missed the case that
            # matters most -- one asset pulled off the category rate while the
            # rest follow it -- and the header then printed the category
            # figure with nothing to say that an asset was not using it.
            mixed_rates=any(c.rate_info.applied != cat_rate.applied
                            for c in group if not c.retired),
        )
        for f in ("opening", "acquisition", "addition", "repair_actual",
                  "repair_deductible", "repair_capitalized", "disposed",
                  "depreciation", "writeoff", "closing"):
            setattr(cat, f, sum((getattr(c, f) for c in group), ZERO))
        st = statutory(year, code)
        if st.repair_limit is not None:
            cat.repair_limit_pct = st.repair_limit
            cat.repair_limit = money(cat.opening * st.repair_limit)
        cat.monthly = [sum((c.monthly[m] for c in group), ZERO) for m in range(12)]

        # -- control §5.4.1: the balance identity, checked per category -----
        lhs = (cat.opening + cat.acquisition + cat.addition
               + cat.repair_capitalized
               - cat.disposed - cat.depreciation - cat.writeoff)
        if money(lhs) != money(cat.closing):
            raise CalcError(
                f"{code} kateqoriyası üzrə balans uyğun gəlmir: "
                f"{money(lhs)} != {money(cat.closing)}. "
                f"Bu, məlumat deyil, mühərrik xətasıdır."
            )

        # -- control §5.4.1b: the movement statement must meet the residual --
        gross_end = sum((c.gross_end for c in group), ZERO)
        acc_end = sum((c.accumulated_end for c in group), ZERO)
        if money(gross_end - acc_end) != money(cat.closing):
            raise CalcError(
                f"{code} kateqoriyası üzrə hərəkət uyğun gəlmir: ilkin dəyər "
                f"{money(gross_end)} − yığılmış {money(acc_end)} = "
                f"{money(gross_end - acc_end)}, qalıq isə {money(cat.closing)}."
            )
        result.categories.append(cat)

    for f in ("opening", "acquisition", "addition", "repair_actual",
              "repair_limit", "repair_deductible", "repair_capitalized",
              "disposed", "depreciation", "writeoff", "closing"):
        result.totals[f] = sum((getattr(cat, f) for cat in result.categories), ZERO)
    result.monthly = [
        sum((cat.monthly[m] for cat in result.categories), ZERO) for m in range(12)
    ]

    # -- warnings -------------------------------------------------------------
    for cat in result.categories:
        if cat.rate.below_statutory and not cat.mixed_rates:
            result.warnings.append(
                f"{cat.name_az}: tətbiq olunan dərəcə {cat.rate.applied:.0%} "
                f"m.114.3 normasından ({cat.rate.statutory_max:.0%}) aşağıdır — "
                f"bu qanunidir, lakin məntiqli qərar olmalıdır."
            )
        # (the unused-coefficient notice is raised once below, not per category)
        for c in cat.cards:
            if c.retired:
                continue        # a zero row has no rate worth reporting on
            if c.rate_info.source == "asset":
                result.warnings.append(
                    f"{c.inv_no or c.name}: fərdi dərəcə "
                    f"{c.rate_info.applied:.0%} (kateqoriya üzrə "
                    f"{cat.rate.applied:.0%}, hədd {c.rate_info.ceiling:.0%})."
                )
    # One notice for the whole report, not one per category: the same sentence
    # repeated five times is noise, and noise is how a real warning gets missed.
    if mult.coefficient > D("1"):
        unused = [cat for cat in result.categories
                  if not cat.mixed_rates and not cat.rate.coefficient_used
                  and CATEGORY_BY_CODE[cat.code].kind == "ev"]
        if unused:
            result.warnings.append(
                f"{STATUS_NAMES[status_row.status]} əmsalı (×{mult.coefficient}) "
                f"tətbiq olunmayıb — bu haqdır, məcburiyyət deyil. Kateqoriyalar: "
                + ", ".join(f"{cat.name_az} ({cat.rate.applied:.0%} → "
                            f"{cat.rate.ceiling:.0%} mümkündür)" for cat in unused)
            )

    missing_inv = [c for c in result.cards
                   if not c.is_legacy_pool and not c.inv_no and not c.retired]
    if missing_inv:
        result.warnings.append(
            "İnventar nömrəsi olmayan ƏV: "
            + ", ".join(c.name for c in missing_inv)
            + " — kartı redaktə edib nömrə verin («növbəti» düyməsi təklif edir)."
        )
    # The test is named after its own figures rather than a literal "500/5%":
    # once those can be amended, a hardcoded label would go on describing a
    # rule the program is no longer applying.
    label = threshold_label(year)
    label_next = threshold_label(year + 1)
    for c in result.cards:
        if not c.is_legacy_pool and c.cost == ZERO and c.opening > ZERO:
            result.warnings.append(
                f"{c.inv_no or c.name}: ilkin dəyər məlum deyil — {label} "
                f"testinin yalnız {rates.parameter(year, 'threshold_abs'):g} AZN "
                f"hissəsi tətbiq oluna bilər."
            )
    for c in result.threshold_next_cards:
        result.warnings.append(
            f"{c.inv_no or c.name}: il sonuna qalıq {c.closing:.2f} AZN — "
            f"{year + 1}-ci ildə {label_next} həddinə düşəcək "
            f"({c.threshold_next_reason})."
        )
    for c in result.threshold_cards:
        if not c.written_off:
            result.warnings.append(
                f"{c.inv_no or c.name}: {label} həddinə düşür ({c.threshold_reason}), "
                f"lakin writeoffs.tsv-də qərar yoxdur — silinmə tətbiq edilmədi."
            )
    for c in result.cards:
        if not c.disposal_type:
            continue
        if c.gain_loss > ZERO:
            result.disposal_gain += c.gain_loss
        elif c.gain_loss < ZERO:
            result.disposal_loss += -c.gain_loss
        if c.disposal_type == "leqv" and c.gain_loss != ZERO:
            # 144.1.3 sets the gain aside when an asset was destroyed or taken
            # against the owner's will AND the proceeds are reinvested in a
            # like asset by the end of the following year. Too conditional for
            # the engine to decide, so it is raised rather than applied.
            result.warnings.append(
                f"{c.inv_no or c.name}: ləğv edilib. Aktiv sahibinin iradəsindən "
                f"asılı olmayaraq məhv olubsa və daxilolmalar növbəti ilin "
                f"sonunadək analoji aktivə yenidən investisiya edilirsə, "
                f"m.144.1.3-ə görə fərq nəzərə alınmaya bilər — yoxlayın."
            )
    result.carried_from_prev = any(
        c.opening_source == "carried" for c in result.cards)
    _cache[year] = result
    if result.is_closed:
        result.warnings.append(
            f"{year} ili BAĞLIDIR — hesabat arxivdir, dəyişiklik qəbul edilmir (§6)."
        )
    return result


# ---------------------------------------------------------------------------
# The rate each category was actually depreciated at, year after year.
#
# One year at a time answers "what did we apply"; it cannot answer "did we
# apply the same thing we applied last year", and that is where the mistakes
# are. Read across a row -- 20%, 20%, 20%, 18% -- and a year that broke step
# announces itself, without opening four reports and remembering three
# numbers.
#
# Note what such a row is NOT: the norm for that category was 20% in all four
# years. The 18% is an election (§5.2), a decision to accrue below the
# ceiling, so no amount of care with the rate table would have surfaced it.
# The statutory figure is carried alongside for the opposite case -- when the
# LAW moved and the applied rate merely followed.
#
# Derived, never stored (§2): every cell is the same pipeline run again.
# ---------------------------------------------------------------------------


@dataclass
class RateCell:
    year: int
    computed: bool = False            # the year could be calculated at all
    on_books: bool = False            # this category/asset existed that year
    note: str = ""                    # why the cell is empty, when it is
    statutory: Decimal = ZERO         # m.114.3 norm
    coefficient: Decimal = D("1")
    ceiling: Decimal = ZERO
    applied: Decimal = ZERO
    source: str = "norm"              # norm | category | asset
    below_statutory: bool = False     # accruing under the plain norm
    below_ceiling: bool = False       # a coefficient was available, unused
    coefficient_used: bool = False
    law_changed: bool = False         # the norm differs from the year before
    rate_changed: bool = False        # the applied rate differs from the year before
    cards: int = 0                    # live cards behind the figure
    # Which schedule stands behind the percentage. `qma-n` reads 10% in every
    # column from 2001 to 2030, and yet 2026 is a different calculation -- the
    # matrix exists to make a break like that visible, so it may not be the
    # one place that hides it.
    method: str = "azalan"
    term_years: Optional[int] = None
    per_card: bool = False


@dataclass
class RateSeries:
    key: str
    kind: str                         # category | asset
    name: str
    subtitle: str = ""
    law_ref: str = ""
    category: str = ""
    cells: list[RateCell] = field(default_factory=list)
    rate_changed: bool = False        # the applied rate is not constant
    law_changed: bool = False         # the norm is not constant
    assets: list["RateSeries"] = field(default_factory=list)


@dataclass
class RateMatrix:
    years: list[int] = field(default_factory=list)
    closed: list[int] = field(default_factory=list)
    rows: list[RateSeries] = field(default_factory=list)
    failed: dict[int, str] = field(default_factory=dict)


def _cell_from(info: "RateInfo", year: int) -> RateCell:
    return RateCell(
        year=year, computed=True, on_books=True,
        statutory=info.statutory_max, coefficient=info.coefficient,
        ceiling=info.ceiling, applied=info.applied, source=info.source,
        below_statutory=info.below_statutory, below_ceiling=info.below_ceiling,
        coefficient_used=info.coefficient_used,
        method=info.method, term_years=info.term_years, per_card=info.per_card,
    )


def _mark_changes(series: RateSeries) -> None:
    """Flag every cell whose figures moved since the previous year on the books.

    Compared against the previous cell that HAS figures, not the previous
    column: an asset that sat off the books for a year would otherwise report
    a change on its return that never happened.
    """
    prev = None
    for cell in series.cells:
        if not cell.on_books:
            continue
        if prev is not None:
            cell.rate_changed = (cell.applied != prev.applied
                                 or cell.method != prev.method)
            cell.law_changed = (cell.statutory != prev.statutory
                                or cell.method != prev.method)
            series.rate_changed |= cell.rate_changed
            series.law_changed |= cell.law_changed
        prev = cell


def rate_matrix(data: ClientData, years: list[int]) -> RateMatrix:
    """Applied rates across several years, by category and by deviating asset.

    A year that cannot be computed (no taxpayer status yet, an election above
    the ceiling) is reported as such and does not take the rest of the table
    down with it -- the point of the report is to find exactly that kind of
    thing.
    """
    years = sorted(years)
    out = RateMatrix(years=years, closed=sorted(data.closed_years() & set(years)))
    cache: dict[int, YearResult] = {}
    per_year: dict[int, YearResult] = {}
    for y in years:
        try:
            per_year[y] = compute_year(data, y, cache)
        except (CalcError, LookupError) as e:
            out.failed[y] = str(e)

    # An asset earns its own row once it has ever been pulled off the category
    # rate. Showing every card would bury the answer: on a batch of 240
    # identical fridges (§4) the interesting row is the one that differs.
    deviating: dict[str, tuple[str, str, str]] = {}      # aid -> (cat, inv, name)
    for res in per_year.values():
        for card in res.cards:
            info = card.rate_info
            if info is not None and info.source == "asset":
                deviating.setdefault(card.asset_id,
                                     (card.category, card.inv_no, card.name))

    for code in EV_CODES + QMA_CODES:
        cat_name = CATEGORY_BY_CODE[code].name_az
        series = RateSeries(key=code, kind="category", name=cat_name,
                            law_ref=rates.LAW_REF.get(code, ""), category=code)
        seen = False
        for y in years:
            res = per_year.get(y)
            if res is None:
                series.cells.append(RateCell(year=y, note=out.failed.get(y, "")))
                continue
            cat = next((c for c in res.categories if c.code == code), None)
            if cat is None:
                series.cells.append(RateCell(year=y, computed=True))
                continue
            seen = True
            cell = _cell_from(cat.rate, y)
            cell.cards = sum(1 for c in cat.cards if not c.retired)
            series.cells.append(cell)
        if not seen:
            continue
        _mark_changes(series)

        for aid, (acat, inv, name) in deviating.items():
            if acat != code:
                continue
            sub = RateSeries(key=aid, kind="asset", name=name,
                             subtitle=inv, category=code)
            for y in years:
                res = per_year.get(y)
                if res is None:
                    sub.cells.append(RateCell(year=y, note=out.failed.get(y, "")))
                    continue
                card = next((c for c in res.cards if c.asset_id == aid), None)
                if card is None or card.rate_info is None or card.retired:
                    sub.cells.append(RateCell(year=y, computed=True))
                    continue
                sub.cells.append(_cell_from(card.rate_info, y))
            _mark_changes(sub)
            series.assets.append(sub)
        series.assets.sort(key=lambda s: (s.subtitle, s.name))
        out.rows.append(series)

    return out

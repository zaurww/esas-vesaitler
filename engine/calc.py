"""The year pipeline (CLAUDE.md §5.3). Stateless: events in, computation out.

    1. opening_residual
    2. + acquisitions          bought this year, FULL annual rate, no proration
    3. + capitalized_repair    art. 115 excess over the group limit
    4. - disposed_residual     residual of assets that left
       = base
    5. threshold_test          against step 1, BEFORE any depreciation
    6. x applied_rate          depreciation for the year
    7. = closing_residual
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .model import ClientData
from .rates import (
    CATEGORIES, CATEGORY_BY_CODE, ENGINE_VERSION, EV_CODES, FORMAT_VERSION,
    STATUS_NAMES, THRESHOLD_ABS, THRESHOLD_PCT, multiplier, statutory,
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
    repair_actual: Decimal = ZERO
    repair_deductible: Decimal = ZERO
    repair_capitalized: Decimal = ZERO
    disposed: Decimal = ZERO
    base: Decimal = ZERO
    rate: Decimal = ZERO
    depreciation: Decimal = ZERO
    writeoff: Decimal = ZERO
    closing: Decimal = ZERO

    threshold_hit: bool = False       # opening residual trips it -> this year
    threshold_reason: str = ""
    threshold_next: bool = False      # closing residual trips it -> next year
    threshold_next_reason: str = ""
    written_off: bool = False
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
    def gross_start(self) -> Decimal:
        if self.acquisition > ZERO and self.opening == ZERO:
            return ZERO                       # acquired during the year
        return self.cost if self.cost > ZERO else self.opening

    @property
    def gross_in(self) -> Decimal:
        acq = self.acquisition if self.opening == ZERO else ZERO
        return acq + self.repair_capitalized

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


@dataclass
class YearResult:
    client_name: str
    voen: str
    slug: str
    year: int
    is_closed: bool
    status: str
    status_name: str
    engine_version: str
    format_version: int
    categories: list[CategoryResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    totals: dict[str, Decimal] = field(default_factory=dict)
    monthly: list[Decimal] = field(default_factory=list)

    @property
    def cards(self) -> list[CardResult]:
        return [c for cat in self.categories for c in cat.cards]

    @property
    def threshold_cards(self) -> list[CardResult]:
        return [c for c in self.cards if c.threshold_hit]

    @property
    def threshold_next_cards(self) -> list[CardResult]:
        return [c for c in self.cards if c.threshold_next]


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


def threshold_test(card: "CardResult", residual: Decimal) -> tuple[bool, str]:
    """The 500 AZN / 5%-of-initial-cost test (art. 114).

    A legacy pool row carries no initial cost of its own, so only the flat
    500 AZN half of the test applies to it (§6.1).
    """
    if residual <= ZERO:
        return False, ""
    reasons = []
    if residual < THRESHOLD_ABS:
        reasons.append(f"qalıq {residual:.2f} < {THRESHOLD_ABS} AZN")
    if not card.is_legacy_pool and card.cost > ZERO \
            and residual < card.cost * THRESHOLD_PCT:
        reasons.append(
            f"qalıq {residual:.2f} < ilkin dəyərin 5%-i "
            f"({money(card.cost * THRESHOLD_PCT)} AZN)"
        )
    return bool(reasons), "; ".join(reasons)


def compute_year(data: ClientData, year: int) -> YearResult:
    status_row = data.status_for(year)
    if status_row is None:
        raise CalcError(
            f"нет строки в taxpayer_status.tsv за {year} год — "
            f"без статуса предпринимателя коэффициент к норме неизвестен"
        )

    mult = multiplier(year, status_row.status)
    result = YearResult(
        client_name=data.client_name,
        voen=data.voen,
        slug=data.slug,
        year=year,
        is_closed=year in data.closed_years(),
        status=status_row.status,
        status_name=STATUS_NAMES[status_row.status],
        engine_version=ENGINE_VERSION,
        format_version=data.format_version,
    )

    assets = {a.asset_id: a for a in data.assets}
    opening = {ob.asset_id: ob for ob in data.opening_balances if ob.year == year}
    disposals = {d.asset_id: d for d in data.disposals
                 if d.date is not None and d.date.year == year}
    writeoffs = {w.asset_id for w in data.writeoffs if w.year == year}
    repairs: dict[str, Decimal] = {}
    for r in data.repairs:
        if r.year == year:
            repairs[r.asset_id] = repairs.get(r.asset_id, ZERO) + r.amount

    # -- rate resolution ----------------------------------------------------
    # The entrepreneur coefficient raises the CEILING; it is a right, not a
    # duty, so it is never applied on its own. With no election the plain
    # article 114.3 norm applies -- the engine must not decide to double a
    # client's depreciation for them.
    # The most specific election wins: the asset's own, then the category's.
    def resolve_rate(code: str, asset_id: str = "") -> RateInfo:
        st = statutory(year, code)
        if st.max_rate is None:
            raise CalcError(
                f"{code}: ставка выводится из срока использования (FİM) — этап 1b"
            )
        ceiling = min(st.max_rate * mult.coefficient, D("1"))
        election = data.election_for(year, code, asset_id)
        applied = election.applied_rate if election else st.max_rate
        if applied > ceiling:
            where = f"{election.asset_id}: " if election and election.asset_id else ""
            raise CalcError(
                f"{code}: {where}выбранная ставка {applied:%} превышает потолок "
                f"{ceiling:%} ({st.max_rate:%} × {mult.coefficient} за {year} год). "
                f"Расчёт остановлен — это привело бы к незаконной декларации."
            )
        if applied < ZERO:
            raise CalcError(f"{code}: отрицательная ставка {applied}")
        return RateInfo(
            category=code, statutory_max=st.max_rate, statutory_year=st.effective_year,
            status=status_row.status, coefficient=mult.coefficient, ceiling=ceiling,
            applied=applied, elected=election is not None,
            below_ceiling=applied < ceiling,
            below_statutory=applied < st.max_rate,
            coefficient_used=applied > st.max_rate,
            source=("asset" if election and election.asset_id
                    else "category" if election else "norm"),
        )

    priceable = {c.code for c in CATEGORIES
                 if c.kind == "ev" and statutory(year, c.code).max_rate is not None}

    # -- step 1: opening balances and acquisitions --------------------------
    cards: dict[str, CardResult] = {}
    for aid, asset in assets.items():
        if CATEGORY_BY_CODE[asset.category].kind != "ev":
            continue
        ob = opening.get(aid)
        acq = ZERO
        if asset.in_date is not None and asset.in_date.year == year:
            acq = asset.cost
        if ob is None and acq == ZERO:
            continue  # the asset does not exist in this year yet, or any more
        cards[aid] = CardResult(
            asset_id=aid, inv_no=asset.inv_no, name=asset.name,
            category=asset.category, in_date=asset.in_date, cost=asset.cost,
            is_legacy_pool=asset.is_legacy_pool,
            opening=ob.residual if ob else ZERO,
            acquisition=acq,
        )

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
                f"{c.inv_no or c.asset_id}: категория {c.category} пока не "
                f"поддерживается (ставка из срока использования, этап 1b)"
            )
        c.rate_info = resolve_rate(c.category, c.asset_id)
        disp = disposals.get(c.asset_id)
        if disp is not None:
            c.disposal_type = disp.type
            c.disposal_date = disp.date
            c.proceeds = disp.proceeds
            c.disposed = c.opening + c.acquisition + c.repair_capitalized
            c.gain_loss = disp.proceeds - c.disposed
            c.base = ZERO
            c.closing = ZERO
            c.monthly = [ZERO] * 12
            continue

        c.base = c.opening + c.acquisition + c.repair_capitalized

        # step 5: the 500/5% test runs on the pre-depreciation residual,
        # measured against the asset's initial cost
        c.threshold_hit, c.threshold_reason = threshold_test(c, c.opening)

        if c.threshold_hit and c.asset_id in writeoffs:
            c.written_off = True
            c.writeoff = money(c.base)
            c.depreciation = ZERO
            c.closing = ZERO
        else:
            info = c.rate_info
            c.rate = info.applied
            c.depreciation = money(c.base * info.applied)
            if c.depreciation > c.base:
                c.depreciation = money(c.base)
            c.closing = money(c.base - c.depreciation)
        c.monthly = split_monthly(c.depreciation)

        # Same test against the closing residual. That residual becomes next
        # year's opening balance, so this is a reliable forecast of which
        # assets will fall under the threshold in the year ahead. It does NOT
        # write anything off now -- see CLAUDE.md §12.6.
        if not c.written_off:
            c.threshold_next, c.threshold_next_reason = threshold_test(c, c.closing)

    # -- roll the cards up into categories ----------------------------------
    for code in EV_CODES:
        group = sorted(
            (c for c in cards.values() if c.category == code),
            key=lambda c: (not c.is_legacy_pool, c.inv_no, c.name),
        )
        if not group or code not in priceable:
            continue
        cat = CategoryResult(
            code=code,
            name_az=CATEGORY_BY_CODE[code].name_az,
            name_ru=CATEGORY_BY_CODE[code].name_ru,
            rate=resolve_rate(code),          # the category default
            cards=group,
            mixed_rates=len({c.rate_info.applied for c in group}) > 1,
        )
        for f in ("opening", "acquisition", "repair_actual", "repair_deductible",
                  "repair_capitalized", "disposed", "depreciation", "writeoff", "closing"):
            setattr(cat, f, sum((getattr(c, f) for c in group), ZERO))
        st = statutory(year, code)
        if st.repair_limit is not None:
            cat.repair_limit_pct = st.repair_limit
            cat.repair_limit = money(cat.opening * st.repair_limit)
        cat.monthly = [sum((c.monthly[m] for c in group), ZERO) for m in range(12)]

        # -- control §5.4.1: the balance identity, checked per category -----
        lhs = (cat.opening + cat.acquisition + cat.repair_capitalized
               - cat.disposed - cat.depreciation - cat.writeoff)
        if money(lhs) != money(cat.closing):
            raise CalcError(
                f"баланс не сошёлся по категории {code}: "
                f"{money(lhs)} != {money(cat.closing)}. "
                f"Это ошибка движка, а не данных."
            )

        # -- control §5.4.1b: the movement statement must meet the residual --
        gross_end = sum((c.gross_end for c in group), ZERO)
        acc_end = sum((c.accumulated_end for c in group), ZERO)
        if money(gross_end - acc_end) != money(cat.closing):
            raise CalcError(
                f"движение не сошлось по категории {code}: первоначальная "
                f"{money(gross_end)} − накопленная {money(acc_end)} = "
                f"{money(gross_end - acc_end)}, а остаток {money(cat.closing)}."
            )
        result.categories.append(cat)

    for f in ("opening", "acquisition", "repair_actual", "repair_limit",
              "repair_deductible", "repair_capitalized", "disposed",
              "depreciation", "writeoff", "closing"):
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
                f"bu qanunidir, lakin şüurlu qərar olmalıdır."
            )
        # (the unused-coefficient notice is raised once below, not per category)
        for c in cat.cards:
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
                  if not cat.mixed_rates and not cat.rate.coefficient_used]
        if unused:
            result.warnings.append(
                f"{STATUS_NAMES[status_row.status]} əmsalı (×{mult.coefficient}) "
                f"tətbiq olunmayıb — bu haqdır, məcburiyyət deyil. Kateqoriyalar: "
                + ", ".join(f"{cat.name_az} ({cat.rate.applied:.0%} → "
                            f"{cat.rate.ceiling:.0%} mümkündür)" for cat in unused)
            )

    for c in result.cards:
        if not c.is_legacy_pool and c.cost == ZERO and c.opening > ZERO:
            result.warnings.append(
                f"{c.inv_no or c.name}: ilkin dəyər məlum deyil — 500/5% "
                f"testinin yalnız 500 AZN hissəsi tətbiq oluna bilər."
            )
    for c in result.threshold_next_cards:
        result.warnings.append(
            f"{c.inv_no or c.name}: il sonuna qalıq {c.closing:.2f} AZN — "
            f"{year + 1}-ci ildə 500/5% həddinə düşəcək ({c.threshold_next_reason})."
        )
    for c in result.threshold_cards:
        if not c.written_off:
            result.warnings.append(
                f"{c.inv_no or c.name}: 500/5% həddinə düşür ({c.threshold_reason}), "
                f"lakin writeoffs.tsv-də qərar yoxdur — silinmə tətbiq edilmədi."
            )
    for c in result.cards:
        if c.disposal_type and c.gain_loss != ZERO:
            result.open_questions.append(
                f"{c.inv_no or c.name}: satışdan {'gəlir' if c.gain_loss > 0 else 'zərər'} "
                f"{abs(c.gain_loss):.2f} AZN (satış {c.proceeds:.2f} − qalıq {c.disposed:.2f}). "
                f"Bəyannamədə əks etdirilməsi həll olunmayıb — CLAUDE.md §12.1."
            )
    if result.is_closed:
        result.warnings.append(
            f"{year} ili BAĞLIDIR — hesabat arxivdir, dəyişiklik qəbul edilmir (§6)."
        )
    return result

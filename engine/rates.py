"""Article 114 rates, article 115 repair limits, entrepreneur coefficients.

LIVES IN THE ENGINE, NOT IN THE CLIENT CONFIG (CLAUDE.md §5.1).
Rows for past years are NEVER edited, only appended with a higher
effective_year. Otherwise an engine update would retroactively change a
return that has already been filed.
"""

from decimal import Decimal
from typing import Dict, List, NamedTuple

D = Decimal

ENGINE_VERSION = "0.1.0"
FORMAT_VERSION = 1

# One-off write-off threshold (art. 114)
THRESHOLD_ABS = D("500")
THRESHOLD_PCT = D("0.05")


class Category(NamedTuple):
    code: str
    name_az: str
    name_ru: str
    kind: str  # "ev" | "qma"


CATEGORIES: List[Category] = [
    Category("bt", "Binalar, tikililər", "Здания, сооружения", "ev"),
    Category("ma", "Maşınlar, avadanlıq", "Машины, оборудование", "ev"),
    Category("nv", "Nəqliyyat vasitələri", "Транспортные средства", "ev"),
    Category("ym", "Yük maşınları", "Грузовые машины", "ev"),
    Category("yt", "Yüksək texnologiya", "Высокие технологии", "ev"),
    Category("dg", "Digər əsas vəsaitlər", "Прочие основные средства", "ev"),
    Category("it", "İcarəyə götürülmüş ƏV-in təmiri", "Ремонт арендованных ОС", "ev"),
    Category("qma-m", "QMA — FİM məlum", "НМА — срок известен", "qma"),
    Category("qma-n", "QMA — FİM nəməlum", "НМА — срок неизвестен", "qma"),
]

CATEGORY_BY_CODE: Dict[str, Category] = {c.code: c for c in CATEGORIES}
EV_CODES = [c.code for c in CATEGORIES if c.kind == "ev"]


class RateRow(NamedTuple):
    effective_year: int
    category: str
    max_rate: Decimal | None  # None => rate is derived from useful life (FİM)
    repair_limit: Decimal | None


# TODO §12.2 -- confirm effective_year against the current tax code wording.
#
# Two kinds of change touch this table, and they are NOT the same:
#   * the law changes  -> APPEND a row with a higher effective_year, so past
#                         years keep computing the way they were filed;
#   * we transcribed it wrong -> EDIT the row in place, because every year
#                         computed from it was wrong. Closed years stay safe
#                         (their balances are stored facts), and `ev.py verify`
#                         will report the difference -- which is the point.
STATUTORY_RATES: List[RateRow] = [
    RateRow(2001, "bt", D("0.07"), D("0.02")),
    RateRow(2001, "ma", D("0.20"), D("0.05")),
    RateRow(2001, "nv", D("0.25"), D("0.05")),  # corrected from 3%
    RateRow(2001, "ym", D("0.25"), D("0.08")),  # TODO §12.3 -- verify this 8%
    RateRow(2001, "yt", D("0.25"), D("0.03")),
    RateRow(2001, "dg", D("0.20"), D("0.03")),
    RateRow(2001, "it", None, D("0.03")),       # 1/MAX(FİM;5)
    RateRow(2001, "qma-m", None, None),         # 1/FİM
    RateRow(2001, "qma-n", D("0.10"), None),
]


class MultiplierRow(NamedTuple):
    effective_year: int
    status: str
    coefficient: Decimal


# TODO §12.2/§12.3 -- confirm the start year and the x1.5 coefficient for kicik.
MULTIPLIERS: List[MultiplierRow] = [
    MultiplierRow(2020, "mikro", D("2.0")),
    MultiplierRow(2020, "kicik", D("1.5")),
    MultiplierRow(2020, "orta", D("1.0")),
    MultiplierRow(2020, "iri", D("1.0")),
]

STATUS_NAMES = {
    "mikro": "Mikro sahibkar",
    "kicik": "Kiçik sahibkar",
    "orta": "Orta sahibkar",
    "iri": "İri sahibkar",
}


def _latest(rows, year: int, key_fn, key_value):
    """Row with the greatest effective_year <= year."""
    found = None
    for r in rows:
        if key_fn(r) != key_value or r.effective_year > year:
            continue
        if found is None or r.effective_year > found.effective_year:
            found = r
    return found


def statutory(year: int, category: str) -> RateRow:
    row = _latest(STATUTORY_RATES, year, lambda r: r.category, category)
    if row is None:
        raise LookupError(
            f"нет статутной ставки для категории {category!r} на {year} год"
        )
    return row


def multiplier(year: int, status: str) -> MultiplierRow:
    row = _latest(MULTIPLIERS, year, lambda r: r.status, status)
    if row is None:
        raise LookupError(
            f"нет коэффициента для статуса {status!r} на {year} год"
        )
    return row

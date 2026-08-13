"""Article 114 rates, article 115 repair limits, entrepreneur coefficients.

LIVES IN THE ENGINE, NOT IN THE CLIENT CONFIG (CLAUDE.md §5.1).
Rows for past years are NEVER edited, only appended with a higher
effective_year. Otherwise an engine update would retroactively change a
return that has already been filed.
"""

from decimal import Decimal
from typing import Dict, List, NamedTuple

D = Decimal

ENGINE_VERSION = "0.9.0"
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
    # Art. 115.1 sets the repair limit by referring to article 114.3.x, and
    # trucks are not a category of their own there -- they are 114.3.3
    # nəqliyyat vasitələri, so 5%, not the 8% carried over from the source
    # workbook. The code is kept because client data already uses it.
    RateRow(2001, "ym", D("0.25"), D("0.05")),
    # 114.3.2-1 (high-tech computing) is NOT named in 115.1, so its repair
    # limit is unresolved -- see §12.3. 3% is the source workbook's figure.
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


# ---------------------------------------------------------------------------
# Rows entered by the owner, read from `rates.tsv` / `coefficients.tsv` next to
# the engine. They are ONE FILE PER INSTALLATION, deliberately not per client:
# the tax code is the same for every client, and a per-client copy would give
# five clients five different readings of the law.
#
# Kept separate from the defaults above so an engine update can ship corrected
# defaults without erasing what the owner typed. For the same
# (effective_year, category) the owner's row wins, and the report says so.
# ---------------------------------------------------------------------------

USER_RATES: List[RateRow] = []
USER_MULTIPLIERS: List[MultiplierRow] = []
USER_SOURCE: set = set()          # keys that came from the files, for the UI

RATES_HEADER = ["effective_year", "category", "max_rate", "repair_limit", "note"]
COEFF_HEADER = ["effective_year", "status", "coefficient", "note"]


def _num(v: str) -> Decimal | None:
    v = (v or "").strip().replace(",", ".")
    return None if v in ("", "-") else D(v)


def refresh(root) -> None:
    """Re-read the owner's rate files. Called before every calculation, so an
    edit takes effect on the next page load without restarting anything."""
    from .storage import read_tsv          # local import: storage imports us
    from pathlib import Path

    root = Path(root)
    USER_RATES.clear()
    USER_MULTIPLIERS.clear()
    USER_SOURCE.clear()

    for r in read_tsv(root / "rates.tsv"):
        cat = (r.get("category") or "").strip()
        if cat not in CATEGORY_BY_CODE:
            raise ValueError(f"rates.tsv: naməlum kateqoriya {cat!r}")
        year = int(r["effective_year"])
        USER_RATES.append(RateRow(year, cat, _num(r.get("max_rate", "")),
                                  _num(r.get("repair_limit", ""))))
        USER_SOURCE.add(("rate", year, cat))

    for r in read_tsv(root / "coefficients.tsv"):
        st = (r.get("status") or "").strip()
        if st not in STATUS_NAMES:
            raise ValueError(f"coefficients.tsv: naməlum status {st!r}")
        year = int(r["effective_year"])
        USER_MULTIPLIERS.append(MultiplierRow(year, st, D(r["coefficient"])))
        USER_SOURCE.add(("coef", year, st))


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
    """The owner's rows take precedence over the shipped defaults."""
    row = _latest(USER_RATES, year, lambda r: r.category, category)
    base = _latest(STATUTORY_RATES, year, lambda r: r.category, category)
    if row is None:
        row = base
    elif base is not None and row.effective_year >= base.effective_year:
        # a partially filled row falls back to the default for the blank field
        row = RateRow(row.effective_year, category,
                      row.max_rate if row.max_rate is not None else base.max_rate,
                      row.repair_limit if row.repair_limit is not None
                      else base.repair_limit)
    if row is None:
        raise LookupError(
            f"нет статутной ставки для категории {category!r} на {year} год"
        )
    return row


def multiplier(year: int, status: str) -> MultiplierRow:
    row = _latest(USER_MULTIPLIERS, year, lambda r: r.status, status)
    if row is None:
        row = _latest(MULTIPLIERS, year, lambda r: r.status, status)
    if row is None:
        raise LookupError(
            f"нет коэффициента для статуса {status!r} на {year} год"
        )
    return row


def table_for(year: int) -> list[dict]:
    """The effective table for one year, with where each number came from."""
    out = []
    for c in CATEGORIES:
        try:
            st = statutory(year, c.code)
        except LookupError:
            continue
        user = _latest(USER_RATES, year, lambda r: r.category, c.code)
        out.append({
            "code": c.code, "name_az": c.name_az, "name_ru": c.name_ru,
            "effective_year": st.effective_year,
            "max_rate": None if st.max_rate is None else f"{st.max_rate:.4f}",
            "repair_limit": None if st.repair_limit is None
                            else f"{st.repair_limit:.4f}",
            "source": "user" if user is not None else "engine",
        })
    return out


def coefficients_for(year: int) -> list[dict]:
    out = []
    for status, name in STATUS_NAMES.items():
        m = multiplier(year, status)
        user = _latest(USER_MULTIPLIERS, year, lambda r: r.status, status)
        out.append({"status": status, "name": name,
                    "effective_year": m.effective_year,
                    "coefficient": str(m.coefficient),
                    "source": "user" if user is not None else "engine"})
    return out

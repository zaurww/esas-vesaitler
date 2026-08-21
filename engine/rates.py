"""Article 114 rates, article 115 repair limits, entrepreneur coefficients.

LIVES IN THE ENGINE, NOT IN THE CLIENT CONFIG (CLAUDE.md §5.1).
Rows for past years are NEVER edited, only appended with a higher
effective_year. Otherwise an engine update would retroactively change a
return that has already been filed.
"""

import re

from decimal import Decimal
from typing import Dict, List, NamedTuple

D = Decimal

ENGINE_VERSION = "0.9.2"
FORMAT_VERSION = 1

# Date this table was last checked against the code. Printed on the norms
# screen and on reports: the point is not that it is fresh today, but that a
# user opening the program in three years can SEE how old it is instead of
# trusting a number nobody has looked at since (§7 -- make staleness visible
# rather than pretend it cannot happen).
LAW_REVIEWED = "2026-08-14"


def version_tuple(v: str) -> tuple:
    """Compare two dotted version strings numerically, not lexically.

    Lives beside ENGINE_VERSION rather than wherever first needed it
    (mutate/archive.py, for the "don't import an archive written by a newer
    engine" guard) so a second caller -- web/update.py's "is there a newer
    release" check -- reads the same rule instead of growing its own copy
    that could drift (the class of bug rates.NORM_FILES was named once to
    avoid). A leading "v", as GitHub tags carry (v0.10.0), is stripped so
    both callers can hand it a tag or a bare ENGINE_VERSION alike.
    """
    v = str(v).lstrip("vV")
    out = []
    for part in v.split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out)


class Category(NamedTuple):
    code: str
    name_az: str
    name_ru: str
    kind: str  # "ev" | "qma"
    # Which article the category comes from, so a table can cite the law
    # instead of a year nobody typed.
    law_ref: str = ""


# The nine categories the engine ships with. Frozen: nothing here is ever
# renamed or removed at runtime, only added to (below).
_BUILTIN_CATEGORIES: List[Category] = [
    Category("bt", "Binalar, tikililər", "Здания, сооружения", "ev", "VM m.114.3.1"),
    Category("ma", "Maşınlar, avadanlıq", "Машины, оборудование", "ev", "VM m.114.3.2"),
    Category("nv", "Nəqliyyat vasitələri", "Транспортные средства", "ev", "VM m.114.3.3"),
    Category("ym", "Yük maşınları", "Грузовые машины", "ev", "VM m.114.3.3"),
    Category("yt", "Yüksək texnologiya", "Высокие технологии", "ev", "VM m.114.3.2-1"),
    Category("dg", "Digər əsas vəsaitlər", "Прочие основные средства", "ev", "VM m.114.3.7"),
    # kind="qma", not "ev": the object is a leased FIXED asset, but the
    # DEDUCTION runs through the same exclusions as an intangible -- no
    # coefficient, no 114.8, no ordinary art. 115 limit (§5.1-bis: kind drives
    # those gates, not the label). The reason differs from a real QMA's
    # (art. 118 vs. m.115.6-1 being a self-contained mechanism outside art.
    # 114), so every message a user can see is worded per category, not per
    # kind -- see calc.py, storage.py check_qma, card.js.
    Category("it", "İcarəyə götürülmüş ƏV-in təmiri", "Ремонт арендованных ОС", "qma",
              "VM m.115.3-115.6-1"),
    Category("qma-m", "QMA — FİM məlum", "НМА — срок известен", "qma", "VM m.114.3.6"),
    Category("qma-n", "QMA — FİM nəməlum", "НМА — срок неизвестен", "qma", "VM m.114.3.6"),
]

# LIVE, combined tables: built-in categories plus whatever the owner appended
# in categories.tsv (§12.4-quater -- 114.3.4 `iş heyvanları`, 114.3.5
# `geoloji-kəşfiyyat`, or a category a future amendment adds, none of which
# used to be reachable without a new release). `refresh()` rebuilds and swaps
# these in place, the same discipline as USER_RATES below (§8.0): a reader
# must see the old table or the new one, never a half-built one.
CATEGORIES: List[Category] = list(_BUILTIN_CATEGORIES)
CATEGORY_BY_CODE: Dict[str, Category] = {c.code: c for c in CATEGORIES}
EV_CODES: List[str] = [c.code for c in CATEGORIES if c.kind == "ev"]
QMA_CODES: List[str] = [c.code for c in CATEGORIES if c.kind == "qma"]

# A code an owner may append. Lower-case ASCII only: it is a TSV field, an
# HTML option value, and part of every asset row that uses it forever after,
# so it needs to survive all three without escaping.
CATEGORY_CODE_RE = re.compile(r"[a-z][a-z0-9-]{0,19}")


class RateRow(NamedTuple):
    effective_year: int
    category: str
    max_rate: Decimal | None  # None => rate is derived from useful life (FİM)
    repair_limit: Decimal | None
    note: str = ""
    # WHAT the norm is applied to, which for one category the law changed
    # rather than merely renumbering:
    #   "azalan"  declining balance -- norm x residual, art. 114.4
    #   "duz"     straight line     -- the cost spread over a term, 114.3.6
    # It sits in the table beside the rate because it moves with a year the
    # same way a rate does (qma-n, 2026), so a past year must keep computing
    # the way it was filed. It is NOT in rates.tsv: the owner edits NUMBERS of
    # the law (§5.1-bis), and a method is a form of formula, i.e. code.
    method: str = "azalan"


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

    # Trucks: 115.1 used to set the limit only by pointing at 114.3.x, where
    # trucks are not a category of their own (they are 114.3.3), which is why
    # this said 5%. Law 1033-VIQD of 5 Dec 2023 changed that -- it carved
    # "yük avtomobilləri istisna olmaqla" out of the 5% group and gave trucks
    # their own 8%. So the source workbook's 8% was right for current years
    # and the earlier "correction" to 5% was wrong from 2024 on.
    RateRow(2001, "ym", D("0.25"), D("0.05")),
    RateRow(2024, "ym", D("0.25"), D("0.08"), "1033-VIQD 05.12.2023"),

    # High-tech computing (114.3.2-1) was added to 114.3 in 2017 but was not
    # named in 115.1, leaving its repair limit unresolved -- 3% below was the
    # workbook's guess. Law 406-VIQD of 3 Dec 2021 inserted "114.3.2-1-ci"
    # into 115.1 right after 114.3.2, putting it in the 5% group.
    RateRow(2001, "yt", D("0.25"), D("0.03")),
    RateRow(2022, "yt", D("0.25"), D("0.05"), "406-VIQD 03.12.2021"),
    RateRow(2001, "dg", D("0.20"), D("0.03")),

    # -- İcarəyə götürülmüş ƏV-in təmiri, m.115.6-1 -------------------------
    # Only the common case is modelled: the leased asset is NOT on the
    # lessee's own balance, and the repair is neither reimbursed by the
    # lessor nor offset against rent (that combination is what m.115.6 leaves
    # for m.115.6-1 to govern). The rarer case -- the leased asset carried on
    # the lessee's OWN balance -- falls under m.115.4 instead, with a plain
    # percentage limit by the TYPE of asset leased; that case is out of scope
    # (decided 19.08.2026, CLAUDE.md §10).
    #
    # No percentage limit at all: m.115.6-1 is not "a rate like `dg`", it is
    # a straight-line schedule with no cap -- "illər üzrə mütənasib
    # məbləğlərdə amortizasiya olunmaqla gəlirdən çıxılır", capitalised
    # separately per year of repair ("hər il üzrə ayrıca olaraq
    # kapitallaşdırılır"). repair_limit=None keeps it out of the ordinary
    # art. 115 loop entirely (that loop only runs for a category with a
    # limit), same as it already stays out for a QMA.
    #
    # The term is "bağlanmış müqavilə müddəti ərzində, lakin 5 ildən az
    # olmayaraq" -- the lease contract's term, floored at 5 years. The floor
    # is enforced at DATA ENTRY (storage.check_qma, mutate.assets.create_asset)
    # rather than applied silently at calc time: the number stored in
    # useful_life IS the schedule length, so nothing here ever rewrites a
    # figure the user typed (§2.1). calc.straight_term reads it exactly like
    # `qma-m` reads a FİM.
    RateRow(2001, "it", None, None, "", "duz"),

    # -- Qeyri-maddi aktivlər, 114.3.6 -------------------------------------
    # A known term has always been straight line: "illər üzrə istifadə
    # müddətinə mütənasib məbləğlərlə" -- amounts proportional to the years of
    # the term, which is a schedule and not a rate on a residual.
    #
    # An unknown term was "10 faizədək", a NORM, and a norm goes on the
    # residual (114.4) -- declining balance, with a tail that nothing ever
    # ends: art. 114.8 cuts short a small residual only for `əsas vəsait`, and
    # a QMA is not one (art. 118). Law 297-VIIQD of 9 Dec 2025 closed that: it
    # put "(bu Məcəllənin 114.3.6-cı maddəsinə münasibətdə düz xətt metodu)"
    # into 114.3 -- addressed to the WHOLE of 114.3.6, both halves -- and gave
    # the unknown term a length in 114.3-1.10: ten years. Ten years and ten
    # per cent are the same number, which is what makes the reading hold.
    RateRow(2001, "qma-m", None, None, "", "duz"),          # 1/FİM
    RateRow(2001, "qma-n", D("0.10"), None, "", "azalan"),
    RateRow(2026, "qma-n", D("0.10"), None,
            "297-VIIQD 09.12.2025", "duz"),
]


class MultiplierRow(NamedTuple):
    effective_year: int
    status: str
    coefficient: Decimal
    note: str = ""


# ---------------------------------------------------------------------------
# Numeric parameters of the law that are not per-category rates.
#
# These used to be Python constants, which meant a change in the code could
# only be followed by a new release of this program. That is the wrong
# dependency for a tool that is handed to people and then has to keep working
# without its author, so every figure the tax code fixes lives here instead --
# year-keyed, overridable from parameters.tsv, same as the rates.
#
# The registry is deliberately a lookup rather than named constants: when a
# future amendment introduces another figure, it is one row here plus one use
# site, with no change to the storage format (§7).
# ---------------------------------------------------------------------------

class ParamRow(NamedTuple):
    effective_year: int
    key: str
    value: Decimal
    note: str = ""


PARAM_DEFS: Dict[str, tuple] = {
    # key: (label_az, law_ref, kind) -- kind drives display and validation
    "threshold_abs": ("Birdəfəlik silinmə həddi — məbləğ",
                      "VM m.114.8", "money"),
    "threshold_pct": ("Birdəfəlik silinmə həddi — ilkin dəyərin faizi",
                      "VM m.114.8", "pct"),
    # Straight line needs a length, and for a QMA whose term is unknown the
    # law supplies one. A number, therefore data (§5.1-bis) -- the method that
    # consumes it stays in the engine.
    "qma_term_unknown": ("QMA — istifadə müddəti məlum olmayanlar üçün müddət",
                         "VM m.114.3-1.10", "years"),
}

PARAMETERS: List[ParamRow] = [
    ParamRow(2001, "threshold_abs", D("500")),
    ParamRow(2001, "threshold_pct", D("0.05")),
    # No row before 2026 on purpose: until then an unknown term had no length,
    # it had a rate on the residual. Asking for one earlier is a bug, and
    # `parameter()` says so instead of inventing ten years (§2.1).
    ParamRow(2026, "qma_term_unknown", D("10"), "297-VIIQD 09.12.2025"),
]


# Law 1356-VQD of 30 Nov 2018 added the two coefficient articles, published
# December 2018, so they apply from 2019 -- not 2020, which was a guess.
# Making them available a year earlier cannot change an existing figure: the
# coefficient only ever raises the CEILING, and nothing is doubled without an
# explicit election (§5.2).
MULTIPLIERS: List[MultiplierRow] = [
    MultiplierRow(2019, "mikro", D("2.0"), "1356-VQD 30.11.2018"),
    MultiplierRow(2019, "kicik", D("1.5"), "1356-VQD 30.11.2018"),
    MultiplierRow(2019, "orta", D("1.0")),
    MultiplierRow(2019, "iri", D("1.0")),
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
USER_PARAMETERS: List[ParamRow] = []
USER_SOURCE: set = set()          # keys that came from the files, for the UI

RATES_HEADER = ["effective_year", "category", "max_rate", "repair_limit", "note"]
COEFF_HEADER = ["effective_year", "status", "coefficient", "note"]
PARAM_HEADER = ["effective_year", "key", "value", "note"]
CATEGORIES_HEADER = ["code", "name_az", "name_ru", "kind", "law_ref", "note"]

# Every file that carries the owner's reading of the law. Named once because
# it is read in four places -- refresh, archive export, archive inspect,
# archive import -- and the archive code had already fallen behind: it still
# listed two files after parameters.tsv appeared, so a changed write-off
# threshold would not have travelled with the client. That is precisely the
# silent divergence the archive exists to prevent (§8.2).
NORM_FILES = ("categories.tsv", "rates.tsv", "coefficients.tsv", "parameters.tsv")


def _num(v: str) -> Decimal | None:
    v = (v or "").strip().replace(",", ".")
    return None if v in ("", "-") else D(v)


def refresh(root) -> None:
    """Re-read the owner's rate files. Called before every calculation, so an
    edit takes effect on the next page load without restarting anything.

    The new tables are built to the side and swapped in at the end. Clearing
    the live lists first left a window in which the owner's rows did not
    exist, and a concurrent calculation reading through that window fell back
    to the shipped default -- a WRONG figure, silently, which is the one
    failure mode §2.1 refuses. Measured before the fix: with one owner row for
    `ym`, a reader running beside 200 refreshes saw the default 8% instead of
    the owner's 9% in 47% of reads.

    Slice assignment is one operation per list, so a reader sees either the
    old table or the new one, never a half-built one. The caller still holds a
    lock across read-then-compute (web/app.py) -- that is a different problem:
    this only guarantees each table is never torn.
    """
    from .storage import read_tsv          # local import: storage imports us
    from pathlib import Path

    root = Path(root)
    new_rates: List[RateRow] = []
    new_mult: List[MultiplierRow] = []
    new_params: List[ParamRow] = []
    new_source: set = set()

    # -- categories: built-ins plus whatever the owner appended -------------
    # Read first: rates.tsv below validates its `category` column against
    # this, so a category and its rate can be added and take effect together.
    new_categories: List[Category] = list(_BUILTIN_CATEGORIES)
    new_by_code: Dict[str, Category] = {c.code: c for c in new_categories}
    for r in read_tsv(root / "categories.tsv"):
        code = (r.get("code") or "").strip()
        if not CATEGORY_CODE_RE.fullmatch(code):
            raise ValueError(
                f"categories.tsv: kod {code!r} yalnız kiçik latın hərfləri, "
                f"rəqəm və defisdən ibarət ola bilər"
            )
        if code in new_by_code:
            raise ValueError(f"categories.tsv: kod artıq mövcuddur: {code!r}")
        name_az = (r.get("name_az") or "").strip()
        if not name_az:
            raise ValueError(f"categories.tsv: {code!r} üçün ad boşdur")
        kind = (r.get("kind") or "").strip()
        if kind != "ev":
            # QMA's schedule is straight line with the term coming from the
            # card (FİM) or the qma_term_unknown parameter -- a form of
            # formula, which §5.1-bis keeps out of data. A category added
            # here would silently get "azalan" (RateRow's field default,
            # since rates.tsv carries no method column) -- the wrong method
            # for a real QMA, not merely an unsupported one.
            raise ValueError(
                f"categories.tsv: {code!r} — kind yalnız 'ev' ola bilər"
            )
        cat_obj = Category(code, name_az, (r.get("name_ru") or "").strip(),
                           kind, (r.get("law_ref") or "").strip())
        new_categories.append(cat_obj)
        new_by_code[code] = cat_obj
    new_ev = [c.code for c in new_categories if c.kind == "ev"]
    new_qma = [c.code for c in new_categories if c.kind == "qma"]

    for r in read_tsv(root / "rates.tsv"):
        cat = (r.get("category") or "").strip()
        if cat not in new_by_code:
            raise ValueError(f"rates.tsv: naməlum kateqoriya {cat!r}")
        year = int(r["effective_year"])
        new_rates.append(RateRow(year, cat, _num(r.get("max_rate", "")),
                                 _num(r.get("repair_limit", "")),
                                 (r.get("note") or "").strip()))
        new_source.add(("rate", year, cat))

    for r in read_tsv(root / "coefficients.tsv"):
        st = (r.get("status") or "").strip()
        if st not in STATUS_NAMES:
            raise ValueError(f"coefficients.tsv: naməlum status {st!r}")
        year = int(r["effective_year"])
        new_mult.append(MultiplierRow(year, st, D(r["coefficient"]),
                                      (r.get("note") or "").strip()))
        new_source.add(("coef", year, st))

    for r in read_tsv(root / "parameters.tsv"):
        key = (r.get("key") or "").strip()
        if key not in PARAM_DEFS:
            raise ValueError(f"parameters.tsv: naməlum parametr {key!r}")
        year = int(r["effective_year"])
        new_params.append(ParamRow(year, key, D(str(r["value"]).strip()
                                                .replace(",", ".")),
                                   (r.get("note") or "").strip()))
        new_source.add(("param", year, key))

    # A malformed file raises above, before anything is swapped in: a bad edit
    # leaves the previous table standing rather than emptying it. Categories
    # swap in alongside the rest for the same reason -- these are imported by
    # name in several modules (storage, mutate, calc), so the SAME list/dict
    # objects are mutated in place rather than rebound, or those modules would
    # keep looking at the table from before the refresh.
    CATEGORIES[:] = new_categories
    CATEGORY_BY_CODE.clear()
    CATEGORY_BY_CODE.update(new_by_code)
    EV_CODES[:] = new_ev
    QMA_CODES[:] = new_qma
    USER_RATES[:] = new_rates
    USER_MULTIPLIERS[:] = new_mult
    USER_PARAMETERS[:] = new_params
    USER_SOURCE.clear()
    USER_SOURCE.update(new_source)


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
                      else base.repair_limit,
                      row.note,
                      # rates.tsv has no method column, so an owner row would
                      # otherwise fall to the field default and quietly move a
                      # QMA back onto the declining balance.
                      base.method)
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


def _pct(v: Decimal | None) -> str | None:
    return None if v is None else f"{v:.4f}"


def rate_years(category: str) -> list[int]:
    """Every year the rate for this category changes, oldest first."""
    return sorted({r.effective_year for r in STATUTORY_RATES
                   if r.category == category}
                  | {r.effective_year for r in USER_RATES
                     if r.category == category})


def history(category: str) -> list[dict]:
    """The whole life of one category's rate, as ranges rather than start years.

    "2001" on its own answers nothing; "2001-2025" answers the question the
    user actually has. Built by resolving each change year through statutory(),
    so it cannot drift from what the calculation uses.
    """
    years = rate_years(category)
    out = []
    for i, y in enumerate(years):
        st = statutory(y, category)
        user = _latest(USER_RATES, y, lambda r: r.category, category)
        out.append({
            "since": y,
            "until": years[i + 1] - 1 if i + 1 < len(years) else None,
            "max_rate": _pct(st.max_rate),
            "repair_limit": _pct(st.repair_limit),
            "method": st.method,
            "source": "user" if user is not None else "engine",
            "note": (user.note if user is not None else st.note) or "",
        })
    return out


def table_for(year: int) -> list[dict]:
    """The effective table for one year, with where each number came from.

    `law_ref` and `changes` exist so the UI can stop showing a bare
    effective_year: with a single row the year is noise (and, until §12.2 is
    settled, a placeholder nobody verified), while the article reference is
    the fact the accountant can check.
    """
    out = []
    for c in CATEGORIES:
        try:
            st = statutory(year, c.code)
        except LookupError:
            continue
        user = _latest(USER_RATES, year, lambda r: r.category, c.code)
        years = rate_years(c.code)
        i = max((n for n, y in enumerate(years) if y <= year), default=0)
        out.append({
            "code": c.code, "name_az": c.name_az, "name_ru": c.name_ru,
            "effective_year": st.effective_year,
            "until": years[i + 1] - 1 if i + 1 < len(years) else None,
            "changes": len(years),
            "law_ref": c.law_ref,
            "max_rate": _pct(st.max_rate),
            "repair_limit": _pct(st.repair_limit),
            # Printed beside the rate rather than left implicit: for `qma-n`
            # the same 10% means two different calculations depending on the
            # year, and a screen that shows only "10%" cannot say which.
            "method": st.method,
            "kind": c.kind,
            "source": "user" if user is not None else "engine",
            "note": (user.note if user is not None else st.note) or "",
            "history": history(c.code),
        })
    return out


def parameter(year: int, key: str) -> Decimal:
    """A numeric figure the tax code fixes, as it stood in `year`.

    Fails loudly rather than falling back to a plausible number: a missing
    threshold would otherwise silently write off nothing, or everything.
    """
    row = _latest(USER_PARAMETERS, year, lambda r: r.key, key)
    if row is None:
        row = _latest(PARAMETERS, year, lambda r: r.key, key)
    if row is None:
        raise LookupError(f"{year} ili üçün «{key}» parametri təyin edilməyib")
    return row.value


def param_years(key: str) -> list[int]:
    return sorted({r.effective_year for r in PARAMETERS if r.key == key}
                  | {r.effective_year for r in USER_PARAMETERS if r.key == key})


def parameters_for(year: int) -> list[dict]:
    out = []
    for key, (label, law_ref, kind) in PARAM_DEFS.items():
        user = _latest(USER_PARAMETERS, year, lambda r: r.key, key)
        eff = _latest(USER_PARAMETERS, year, lambda r: r.key, key) \
            or _latest(PARAMETERS, year, lambda r: r.key, key)
        years = param_years(key)
        i = max((n for n, y in enumerate(years) if y <= year), default=0)
        out.append({
            "key": key, "label": label, "law_ref": law_ref, "kind": kind,
            "value": str(parameter(year, key)),
            "effective_year": eff.effective_year if eff else None,
            "until": years[i + 1] - 1 if i + 1 < len(years) else None,
            "changes": len(years),
            "note": (user.note if user is not None else "") or "",
            "source": "user" if user is not None else "engine",
        })
    return out


def coef_years(status: str) -> list[int]:
    return sorted({r.effective_year for r in MULTIPLIERS if r.status == status}
                  | {r.effective_year for r in USER_MULTIPLIERS
                     if r.status == status})


def coef_law_ref(year: int, status: str) -> str:
    """Which article grants the coefficient -- which depends on the year.

    Law 297-VIIQD (9 Dec 2025) inserted a new 114.3-1 (useful lives for the
    straight-line method) and pushed the coefficient articles down one:
    mikro 114.3-1 -> 114.3-2, kicik 114.3-2 -> 114.3-3. Citing the current
    numbering on a 2024 report would send the accountant to the wrong text.
    """
    if status == "mikro":
        return "VM m.114.3-2" if year >= 2026 else "VM m.114.3-1"
    if status == "kicik":
        return "VM m.114.3-3" if year >= 2026 else "VM m.114.3-2"
    return ""


def coefficients_for(year: int) -> list[dict]:
    out = []
    for status, name in STATUS_NAMES.items():
        m = multiplier(year, status)
        user = _latest(USER_MULTIPLIERS, year, lambda r: r.status, status)
        out.append({"status": status, "name": name,
                    "effective_year": m.effective_year,
                    "changes": len(coef_years(status)),
                    "law_ref": coef_law_ref(year, status),
                    "coefficient": str(m.coefficient),
                    "note": (user.note if user is not None else m.note) or "",
                    "source": "user" if user is not None else "engine"})
    return out

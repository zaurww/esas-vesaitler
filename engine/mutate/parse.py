"""Turning what a person typed into what the store holds (§11.1).

On the way in the program accepts what Excel puts on the clipboard -- spaces
for thousands, a comma for the decimal, a currency sign, a day-first date.
Two shapes are refused rather than guessed at, because guessing is wrong by a
factor of a thousand (`1,234`) or by several months (`MM/DD/YYYY`).

On the way out the same file holds the serialisers, including the two that
must NOT be treated as money: a rate is not an amount (§11), and a string
going into config.toml has to survive a company name with quotes in it."""

from __future__ import annotations

import re
import unicodedata

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..rates import CATEGORY_BY_CODE
from ..storage import DataError

D = Decimal

_NUM_NOISE = re.compile(r"[\s  '`]|AZN|azn|₼")


def _normalise_number(raw: str, field: str) -> str:
    """Turn what Excel puts on the clipboard into something Decimal accepts.

    A pasted money column arrives as the user SEES it -- "1 234,56" here,
    "1,234.56" on an English machine, with non-breaking spaces for grouping.
    Rejecting all of that would make pasting useless, but guessing is worse:
    "1,234" is 1234 in one locale and 1.234 in the other, and quietly picking
    one would store a number a thousand times off. So the unambiguous shapes
    are accepted and the one genuinely ambiguous shape is refused out loud
    (§2.1).
    """
    s = _NUM_NOISE.sub("", raw)
    if not s:
        return "0"
    neg = s.startswith("-")
    s = s.lstrip("+-")
    commas, dots = s.count(","), s.count(".")

    if commas and dots:
        # Both present: whichever comes last is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif commas > 1:
        s = s.replace(",", "")                     # 1,234,567 -- grouping
    elif commas == 1:
        head, _, tail = s.partition(",")
        if len(tail) == 3 and head[-1:].isdigit():
            raise DataError(
                f"{field}: {raw.strip()!r} birmənalı deyil — «,» burada həm "
                f"onluq ayırıcı (1,234 = 1.234), həm də minlik ayırıcı "
                f"(1,234 = 1234) ola bilər. Onluq hissəni nöqtə ilə yazın."
            )
        s = s.replace(",", ".")
    elif dots > 1:
        s = s.replace(".", "")                     # 1.234.567 -- grouping

    try:
        d = D(("-" if neg else "") + s)
    except InvalidOperation:
        raise DataError(f"{field}: rəqəm deyil — {raw.strip()!r}") from None
    return str(d)


def dec(value: Any, field: str, *, allow_zero: bool = True) -> str:
    raw = str(value).strip()
    try:
        d = D(_normalise_number(raw, field) if raw else "0")
    except InvalidOperation:
        raise DataError(f"{field}: rəqəm deyil — {value!r}") from None
    if d < 0 or (not allow_zero and d == 0):
        raise DataError(f"{field}: mənfi və ya sıfır ola bilməz — {d}")
    return f"{d:.2f}"


# Day first, because that is how the date is written here and in the source
# workbooks. Deliberately NOT accepting %m/%d/%Y: "03/05/2023" would then be
# two different dates depending on which pattern matched first, and nothing in
# the cell says which was meant.
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


def iso_date(value: Any, field: str, *, required: bool = True) -> str:
    v = str(value or "").strip()
    if not v:
        if required:
            raise DataError(f"{field}: tarix tələb olunur")
        return ""
    # Excel hands over a datetime as "15.02.2023 0:00" -- drop the time.
    v = v.split()[0] if " " in v else v
    v = v.replace("T", " ").split()[0]
    d = None
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(v, fmt).date()
            break
        except ValueError:
            continue
    if d is None:
        raise DataError(
            f"{field}: tarix anlaşılmadı — {value!r}. "
            f"YYYY-MM-DD və ya GG.AA.YYYY yazın."
        )
    if d > date.today():
        raise DataError(f"{field}: gələcək tarix ola bilməz — {d}")
    return d.isoformat()


def category_of(value: Any, field: str = "category") -> str:
    v = str(value or "").strip()
    if v not in CATEGORY_BY_CODE:
        raise DataError(f"{field}: naməlum kateqoriya {v!r}")
    return v

def _toml_str(value: str) -> str:
    """Quote a value for config.toml. A client name legitimately contains
    «» and " -- unescaped it produced a file tomllib then refused to read."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

def _pct(value: D) -> str:
    """A rate as a percentage, keeping the digits it actually has.

    25% x 1.5 is 37.5%, and rounding that to "38%" in a message is not a
    cosmetic loss: 38% is above the ceiling it is describing.
    """
    return _plain(value * 100) + "%"

def _plain(value: D) -> str:
    """Decimal as a plain string, without exponent and without eating digits.

    `f"{v:f}".rstrip("0")` looks like the obvious way to drop trailing zeros
    and is a trap: "800.000000" loses its own zeros too and is stored as "8".
    Only strip when there is a fractional part to strip.
    """
    s = f"{value:f}"
    return s.rstrip("0").rstrip(".") if "." in s else s

def _rate_or_blank(value: Any) -> str:
    v = str(value or "").strip().replace(",", ".").rstrip("%")
    if v == "":
        return ""
    d = D(v)
    if d > 1:
        d = d / 100                    # accept both 5 and 0.05
    if d < 0 or d > 1:
        raise DataError(f"dərəcə 0 və 1 arasında olmalıdır — {value!r}")
    return f"{d:.4f}".rstrip("0").rstrip(".")

def _fold(text: object) -> str:
    """Casefold a header for comparison, Azerbaijani-safe.

    `"İnv.№".lower()` is NOT `"inv.№"`: the dotted capital İ lowercases to an
    `i` followed by a combining dot above, so a plain comparison misses every
    header that starts with it. The dotted/dotless pair İ i I ı is folded to a
    single `i` and combining marks are dropped. `ə ç ş ğ ö ü` are letters in
    their own right and survive untouched.
    """
    s = str(text or "")
    for ch in "İIı":
        s = s.replace(ch, "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


# People type headers without the Azerbaijani letters all the time -- "Deyer"
# for "Dəyər", "Qaliq" for "Qalıq". A second, blunter fold lets those match
# too. Used only for comparing headers, never for storing anything.
_ASCII = str.maketrans({"ə": "e", "ç": "c", "ş": "s", "ğ": "g", "ö": "o", "ü": "u"})


def _fold2(text: object) -> str:
    return _fold(text).translate(_ASCII)


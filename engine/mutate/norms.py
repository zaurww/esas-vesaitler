"""The owner's edits to the figures of the law (§5.1).

These write to the installation root, not to a client folder: the tax code is
the same for everyone, and a per-client copy would give five clients five
readings of it. Only appending forward is reachable from the interface;
editing the past is a flag, because a form that did both once wrote three rows
nobody had entered."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from .. import rates
from ..rates import CATEGORY_BY_CODE
from ..storage import DataError, read_tsv, write_tsv

from .core import _recompute_everything
from .parse import _plain, _rate_or_blank, category_of

D = Decimal

def set_rate_row(root: Path, slug: str, p: dict) -> str:
    """Add a row to the installation-wide rates.tsv.

    Not per client: the tax code is the same for everyone (§5.1). Rolls back
    if the new table stops any open year from computing.

    APPEND ONLY through the interface. §5.1 keeps in-place correction legal --
    a rate we transcribed wrong makes every year computed from it wrong, so
    the fix has to reach backwards -- but that is the owner's act, carried by
    an engine release or by editing rates.tsv directly. It must not be a
    button, because the one form that did both wrote a year the user never
    typed: the field arrived pre-filled with the engine's placeholder, and
    saving without touching it silently claimed the past as the owner's.
    `allow_past` is the deliberate override, not offered in the UI.
    """
    year = int(p["effective_year"])
    cat = category_of(p.get("category"))
    path = root / "rates.tsv"

    if not p.get("allow_past") and not p.get("remove"):
        years = rates.rate_years(cat)
        newest = max(years) if years else None
        if newest is not None and year <= newest:
            raise DataError(
                f"«{rates.CATEGORY_BY_CODE[cat].name_az}» üzrə {newest}-ci ildən "
                f"qüvvədə olan norma var. Yeni norma {newest + 1} və ya sonrakı "
                f"ildən qüvvəyə minə bilər — keçmiş illər təqdim edilmiş "
                f"bəyannamələrdir və dəyişdirilmir."
            )
        # A row identical to what already applies is not a change; it only
        # turns "proqramdan" into "əl ilə yazılıb" and pretends someone
        # decided something. Refuse it instead of storing noise.
        if newest is not None:
            cur = rates.statutory(year, cat)
            new_max = _rate_or_blank(p.get("max_rate"))
            new_lim = _rate_or_blank(p.get("repair_limit"))
            same_max = new_max == "" or (cur.max_rate is not None
                                         and D(new_max) == cur.max_rate)
            same_lim = new_lim == "" or (cur.repair_limit is not None
                                         and D(new_lim) == cur.repair_limit)
            if same_max and same_lim:
                raise DataError(
                    "Dəyişiklik yoxdur: göstərilən dəyərlər hazırda qüvvədə "
                    "olan norma ilə eynidir."
                )

    before = path.read_bytes() if path.exists() else None
    rows = [{h: r.get(h, "") for h in rates.RATES_HEADER}
            for r in read_tsv(path)]
    rows = [r for r in rows
            if not (r["effective_year"] == str(year) and r["category"] == cat)]
    if not p.get("remove"):
        rows.append({
            "effective_year": str(year), "category": cat,
            "max_rate": _rate_or_blank(p.get("max_rate")),
            "repair_limit": _rate_or_blank(p.get("repair_limit")),
            "note": str(p.get("note", "")).strip(),
        })
    write_tsv(path, rates.RATES_HEADER,
              [[r.get(h, "") for h in rates.RATES_HEADER] for r in rows])
    try:
        _recompute_everything(root)
    except BaseException:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        rates.refresh(root)
        raise
    return f"{cat} {year}"


def set_coefficient_row(root: Path, slug: str, p: dict) -> str:
    """Append-only, for the same reason as set_rate_row above."""
    year = int(p["effective_year"])
    status = str(p.get("status", "")).strip()
    if status not in ("mikro", "kicik", "orta", "iri"):
        raise DataError("Status: mikro | kicik | orta | iri")
    path = root / "coefficients.tsv"

    if not p.get("allow_past") and not p.get("remove"):
        years = rates.coef_years(status)
        newest = max(years) if years else None
        if newest is not None and year <= newest:
            raise DataError(
                f"«{rates.STATUS_NAMES[status]}» üzrə {newest}-ci ildən qüvvədə "
                f"olan əmsal var. Yenisi {newest + 1} və ya sonrakı ildən "
                f"qüvvəyə minə bilər."
            )
        if newest is not None and str(p.get("coefficient", "")).strip():
            if D(str(p["coefficient"]).replace(",", ".")) == \
                    rates.multiplier(year, status).coefficient:
                raise DataError("Dəyişiklik yoxdur: əmsal hazırkı ilə eynidir.")

    before = path.read_bytes() if path.exists() else None
    rows = [{h: r.get(h, "") for h in rates.COEFF_HEADER} for r in read_tsv(path)]
    rows = [r for r in rows
            if not (r["effective_year"] == str(year) and r["status"] == status)]
    if not p.get("remove"):
        rows.append({"effective_year": str(year), "status": status,
                     "coefficient": str(p.get("coefficient", "")).strip(),
                     "note": str(p.get("note", "")).strip()})
    write_tsv(path, rates.COEFF_HEADER,
              [[r.get(h, "") for h in rates.COEFF_HEADER] for r in rows])
    try:
        _recompute_everything(root)
    except BaseException:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        rates.refresh(root)
        raise
    return f"{status} {year}"


def set_parameter_row(root: Path, slug: str, p: dict) -> str:
    """Append a figure of the law (the write-off threshold, and whatever a
    future amendment adds) to the installation-wide parameters.tsv.

    Same append-only rule as the rates: the past is where filed returns live.
    """
    year = int(p["effective_year"])
    key = str(p.get("key", "")).strip()
    if key not in rates.PARAM_DEFS:
        raise DataError(f"Naməlum parametr: {key!r}")
    raw = str(p.get("value", "")).strip().replace(",", ".").rstrip("%")
    if raw == "":
        raise DataError("Dəyər boş ola bilməz")
    value = D(raw)
    kind = rates.PARAM_DEFS[key][2]
    if kind == "pct":
        if value > 1:
            value = value / 100        # accept both 5 and 0.05
        if not (0 <= value <= 1):
            raise DataError("Faiz 0 ilə 100 arasında olmalıdır")
    elif value < 0:
        raise DataError("Məbləğ mənfi ola bilməz")

    path = root / "parameters.tsv"
    if not p.get("allow_past") and not p.get("remove"):
        years = rates.param_years(key)
        newest = max(years) if years else None
        if newest is not None and year <= newest:
            raise DataError(
                f"«{rates.PARAM_DEFS[key][0]}» üzrə {newest}-ci ildən qüvvədə "
                f"olan dəyər var. Yenisi {newest + 1} və ya sonrakı ildən "
                f"qüvvəyə minə bilər."
            )
        if newest is not None and value == rates.parameter(year, key):
            raise DataError("Dəyişiklik yoxdur: dəyər hazırkı ilə eynidir.")

    before = path.read_bytes() if path.exists() else None
    rows = [{h: r.get(h, "") for h in rates.PARAM_HEADER} for r in read_tsv(path)]
    rows = [r for r in rows
            if not (r["effective_year"] == str(year) and r["key"] == key)]
    if not p.get("remove"):
        rows.append({"effective_year": str(year), "key": key,
                     "value": _plain(value),
                     "note": str(p.get("note", "")).strip()})
    write_tsv(path, rates.PARAM_HEADER,
              [[r.get(h, "") for h in rates.PARAM_HEADER] for r in rows])
    try:
        _recompute_everything(root)
    except BaseException:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        rates.refresh(root)
        raise
    return f"{key} {year}"


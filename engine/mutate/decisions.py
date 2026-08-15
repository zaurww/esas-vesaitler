"""Decisions the taxpayer makes, and the act of closing a year.

Status, elected rate, the 500/5% write-off: none of these are derived from
anything -- they are choices, and the engine records them rather than making
them (§5.2, §5.3-bis). Closing a year is the other act: it freezes the facts
and seals the balances (§6.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .. import rates
from ..calc import compute_year
from ..rates import ENGINE_VERSION
from ..storage import DataError, load_client

from .core import guard_open_year, rows_of, save_rows, transaction
from .parse import _pct, _plain, category_of

D = Decimal

def close_year(root: Path, slug: str, p: dict) -> str:
    """Close a year: write its closing balances as next year's opening ones.

    This is the ONLY way balances move between years (CLAUDE.md §6). Nothing
    carries over automatically, because carrying over is what freezes the
    numbers that went into a filed return -- it has to be a deliberate act,
    stamped with who closed it, when, and with which engine version.
    """
    year = int(p["year"])
    data = load_client(root, slug)
    if year in data.closed_years():
        raise DataError(f"{year} ili artıq bağlıdır")
    rates.refresh(root)
    result = compute_year(data, year)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with transaction(root, slug, "year.close") as tx:
        rows = rows_of(root, slug, "opening_balances.tsv")
        n = 0
        for c in result.cards:
            if c.closing == 0 and (c.written_off or c.disposal_type):
                continue                      # the asset has left the books
            rows.append({
                "year": str(year + 1), "asset_id": c.asset_id,
                "category": c.category, "residual": f"{c.closing:.2f}",
                "source": "year_close", "engine_version": ENGINE_VERSION,
                "closed_at": stamp,
            })
            n += 1
        save_rows(root, slug, "opening_balances.tsv", rows)
        tx.log("", f"close {year}", "", f"{n} sətir → {year + 1}")
    return f"{year} → {year + 1}: {n}"


def reopen_year(root: Path, slug: str, p: dict) -> str:
    """Undo a close.

    §6 seals closed years on purpose, but a misclick must not require editing
    files by hand -- that is the very thing the app exists to prevent. The
    reversal is loud: it is named in the changelog, and it throws away the
    stored balances, so the next close recomputes them from scratch.
    """
    year = int(p["year"])
    with transaction(root, slug, "year.reopen") as tx:
        rows = rows_of(root, slug, "opening_balances.tsv")
        kept = [r for r in rows if not (r["year"] == str(year + 1)
                                        and r["source"] == "year_close")]
        removed = len(rows) - len(kept)
        if not removed:
            raise DataError(f"{year} ili bağlı deyil")
        save_rows(root, slug, "opening_balances.tsv", kept)
        tx.log("", f"reopen {year}", f"{removed} sətir", "silindi")
    return f"{year}"


def set_writeoff(root: Path, slug: str, p: dict) -> str:
    """Record (or withdraw) the decision to write an asset off under 500/5%."""
    """Record (or withdraw) the 114.8 write-off for one asset or for many.

    Many matters more than it looks. Every transaction backs the whole client
    folder up, then reloads and recomputes every open year (§8.1) -- correct
    for one decision, absurd forty times over when a workshop's worth of
    tooling crosses the threshold in the same year. Forty backups, forty
    recomputes, forty lines of changelog for what the accountant did as a
    single act.

    So the decision is one transaction whatever its size: all the assets land
    together or none of them do. The changelog still gets a line per asset --
    the grouping is a convenience for the person, not a reason to record less
    about what happened.
    """
    year = int(p["year"])
    ids = p.get("asset_ids")
    if ids is None:
        ids = [p["asset_id"]]
    elif isinstance(ids, str):
        ids = [i for i in (s.strip() for s in ids.split(",")) if i]
    ids = [str(i) for i in ids]
    if not ids:
        raise DataError("silinmə üçün ƏV seçilməyib")

    with transaction(root, slug, "writeoff.set") as tx:
        guard_open_year(root, slug, year)
        known = {r["asset_id"] for r in rows_of(root, slug, "assets.tsv")}
        missing = [i for i in ids if i not in known]
        if missing:
            raise DataError("ƏV tapılmadı: " + ", ".join(missing))
        rows = rows_of(root, slug, "writeoffs.tsv")
        target = set(ids)
        rows = [r for r in rows
                if not (r["asset_id"] in target and r["year"] == str(year))]
        if p.get("enabled"):
            reason = str(p.get("reason", "")).strip() or \
                "VM m.114 — 500/5% həddi, birdəfəlik silinmə"
            for aid in ids:
                rows.append({"year": str(year), "asset_id": aid, "reason": reason})
                tx.log(aid, f"writeoff {year}", "", reason)
        else:
            for aid in ids:
                tx.log(aid, f"writeoff {year}", "var", "silindi")
        save_rows(root, slug, "writeoffs.tsv", rows)
    return ", ".join(ids)


def set_election(root: Path, slug: str, p: dict) -> str:
    """Set the depreciation rate for a category, or for one asset."""
    year = int(p["year"])
    category = category_of(p.get("category"))
    aid = str(p.get("asset_id", "")).strip()
    with transaction(root, slug, "election.set") as tx:
        guard_open_year(root, slug, year)
        rows = rows_of(root, slug, "rate_elections.tsv")
        rows = [r for r in rows if not (
            r["year"] == str(year) and r["category"] == category
            and r.get("asset_id", "") == aid)]
        value = str(p.get("applied_rate", "")).strip()
        target = aid or category
        if value == "":
            tx.log(aid, f"rate {category} {year}", "var", "silindi")
        else:
            rate = D(value.replace(",", ".").rstrip("%"))
            if rate > 1:
                rate = rate / 100          # accept both 25 and 0.25
            rows.append({"year": str(year), "category": category,
                         "applied_rate": f"{rate:.4f}".rstrip("0").rstrip("."),
                         "asset_id": aid})
            tx.log(aid, f"rate {category} {year}", "", f"{rate:.2%}")
        _ = target
        save_rows(root, slug, "rate_elections.tsv", rows)
    return aid or category

def _ceiling(year: int, category: str, coefficient: D) -> D | None:
    st = rates.statutory(year, category)
    if st.max_rate is None:
        return None
    return min(st.max_rate * coefficient, D("1"))


def set_status(root: Path, slug: str, p: dict) -> str:
    year = int(p["year"])
    status = str(p.get("status", "")).strip()
    if status not in ("mikro", "kicik", "orta", "iri"):
        raise DataError("Status: mikro | kicik | orta | iri")
    use_coefficient = bool(p.get("use_coefficient"))
    coefficient = (rates.multiplier(year, status).coefficient
                   if use_coefficient else D("1"))

    # The lock comes first: a closed year is refused because it is closed, and
    # saying anything else about it -- a rate above its ceiling, say -- names
    # a reason the user could act on when the real one is that the return has
    # been filed.
    guard_open_year(root, slug, year)

    # Lowering the status -- or waiving the coefficient -- lowers the CEILING,
    # and a rate already on file can end up above it. The transaction would
    # catch that anyway and roll back, but the message it produced talked
    # about a depreciation rate the user had not touched, on a form about
    # status. Name the rate that is in the way and where to change it.
    blocked = []
    for e in load_client(root, slug).elections:
        if e.year != year:
            continue
        ceiling = _ceiling(year, e.category, coefficient)
        if ceiling is not None and e.applied_rate > ceiling:
            who = f" ({e.asset_id})" if e.asset_id else ""
            blocked.append(f"{e.category}{who} — {_pct(e.applied_rate)} > "
                           f"{_pct(ceiling)}")
    if blocked:
        raise DataError(
            f"{year}: status dəyişdirilə bilməz, çünki seçilmiş amortizasiya "
            f"dərəcəsi yeni yuxarı həddi aşır — " + "; ".join(blocked) + ". "
            f"Əvvəlcə həmin dərəcəni azaldın (kateqoriya sətrində «dərəcəni "
            f"dəyiş», ƏV kartında «Fərdi dərəcə»), sonra statusu dəyişin."
        )

    with transaction(root, slug, "status.set") as tx:
        guard_open_year(root, slug, year)
        rows = rows_of(root, slug, "taxpayer_status.tsv")
        use = "" if use_coefficient else "0"
        old = next((r for r in rows if r["year"] == str(year)), None)
        if old:
            if old["status"] != status:
                tx.log("", f"status {year}", old["status"], status)
            if old.get("use_coefficient", "") != use:
                tx.log("", f"əmsal {year}",
                       "istifadə" if old.get("use_coefficient", "") != "0" else "imtina",
                       "istifadə" if use != "0" else "imtina")
            old["status"] = status
            old["basis"] = str(p.get("basis", old.get("basis", ""))).strip()
            old["use_coefficient"] = use
        else:
            rows.append({"year": str(year), "status": status,
                         "basis": str(p.get("basis", "")).strip(),
                         "use_coefficient": use})
            tx.log("", f"status {year}", "", status)
        save_rows(root, slug, "taxpayer_status.tsv", rows)

        # Applying the coefficient stays a decision, never a consequence of
        # typing a status (§5.2) -- the engine has no business doubling a
        # client's depreciation on its own. What moved is WHERE the decision
        # is offered: next to the fact that creates the right, instead of on a
        # separate screen the user has to know exists. That separate screen is
        # exactly what got missed -- "I set kiçik and the 1.5 did not apply".
        # Nothing is ticked by default, so an unanswered form still elects
        # nothing.
        #
        # Only CATEGORY elections are written here. A rate chosen for a single
        # asset is more specific and keeps winning (§5.2), which is how "all
        # the cars at 1.5, except this one" stays expressible.
        chosen = p.get("apply_coefficient_to") or []
        if isinstance(chosen, str):
            chosen = [c for c in chosen.split(",") if c.strip()]
        if chosen and coefficient <= D("1"):
            raise DataError(
                f"{rates.STATUS_NAMES[status]} üçün əmsal yoxdur (×1) — "
                f"tətbiq ediləcək bir şey yoxdur"
            )
        if chosen:
            elections = rows_of(root, slug, "rate_elections.tsv")
            for code in chosen:
                code = category_of(code)
                ceiling = _ceiling(year, code, coefficient)
                if ceiling is None:
                    continue
                elections = [r for r in elections if not (
                    r["year"] == str(year) and r["category"] == code
                    and not r.get("asset_id", ""))]
                elections.append({"year": str(year), "category": code,
                                  "applied_rate": _plain(ceiling), "asset_id": ""})
                tx.log("", f"rate {code} {year}", "", _pct(ceiling))
            save_rows(root, slug, "rate_elections.tsv", elections)
    return status


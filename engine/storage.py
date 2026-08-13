"""Reading and writing a client folder. TSV + TOML, UTF-8 without BOM (§4, §11).

Validation happens ON READ, not only on write: the files sit there in plain
text and users will edit them by hand sooner or later (§3, layer 1).
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .model import (
    Asset, ClientData, Disposal, OpeningBalance, RateElection, Repair,
    TaxpayerStatus, WriteOff,
)
from .rates import CATEGORY_BY_CODE

D = Decimal


class DataError(Exception):
    """Bad client data. Never swallowed silently (§2.1)."""


# ---------------------------------------------------------------- parsing ---

def _dec(value: str, where: str) -> Decimal:
    v = (value or "").strip()
    if v == "":
        return D("0")
    try:
        return D(v.replace(",", "."))
    except InvalidOperation:
        raise DataError(f"{where}: не число: {value!r}") from None


def _date(value: str, where: str) -> date | None:
    v = (value or "").strip()
    if v == "":
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise DataError(f"{where}: дата не в формате YYYY-MM-DD: {value!r}") from None


def _int(value: str, where: str) -> int:
    v = (value or "").strip()
    if v == "":
        raise DataError(f"{where}: пустое целое")
    try:
        return int(v)
    except ValueError:
        raise DataError(f"{where}: не целое: {value!r}") from None


def _category(value: str, where: str) -> str:
    v = (value or "").strip()
    if v not in CATEGORY_BY_CODE:
        raise DataError(
            f"{where}: неизвестная категория {value!r}; "
            f"допустимы: {', '.join(CATEGORY_BY_CODE)}"
        )
    return v


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for i, ln in enumerate(lines[1:], start=2):
        cells = ln.split("\t")
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append({h.strip(): cells[j] for j, h in enumerate(header)})
        rows[-1]["__line__"] = str(i)
        rows[-1]["__file__"] = path.name
    return rows


def write_tsv(path: Path, header: list[str], rows: Iterable[list[Any]]) -> None:
    """Atomic write: either the whole file lands or it is left untouched (§8)."""
    body = ["\t".join(header)]
    for r in rows:
        body.append("\t".join("" if c is None else str(c) for c in r))
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=str(path.parent)
    )
    try:
        tmp.write("\n".join(body) + "\n")
        tmp.close()
        os.replace(tmp.name, path)
    except BaseException:
        os.unlink(tmp.name)
        raise


def append_tsv(path: Path, header: list[str], rows: Iterable[list[Any]]) -> None:
    existing = read_tsv(path)
    out = [[r.get(h, "") for h in header] for r in existing]
    out.extend(rows)
    write_tsv(path, header, out)


# ------------------------------------------------------------------ client ---

def _where(r: dict[str, str]) -> str:
    return f"{r.get('__file__', '?')}:{r.get('__line__', '?')}"


def load_client(root: Path, slug: str) -> ClientData:
    folder = root / "clients" / slug
    if not folder.is_dir():
        raise DataError(f"клиент не найден: {folder}")

    cfg_path = folder / "config.toml"
    if not cfg_path.exists():
        raise DataError(f"нет config.toml в {folder}")
    cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))

    data = ClientData(
        slug=slug,
        client_name=cfg.get("client_name", slug),
        voen=str(cfg.get("voen", "")),
        start_year=int(cfg.get("start_year", 0)),
        format_version=int(cfg.get("format_version", 1)),
    )

    seen_ids: set[str] = set()
    seen_inv: set[str] = set()
    for r in read_tsv(folder / "assets.tsv"):
        w = _where(r)
        aid = r["asset_id"].strip()
        if not aid:
            raise DataError(f"{w}: пустой asset_id")
        if aid in seen_ids:
            raise DataError(f"{w}: дубликат asset_id {aid!r}")
        seen_ids.add(aid)
        inv = r.get("inv_no", "").strip()
        if inv:
            if inv in seen_inv:
                raise DataError(f"{w}: дубликат inv_no {inv!r}")
            seen_inv.add(inv)
        cost = _dec(r.get("cost", ""), w)
        if cost < 0:
            raise DataError(f"{w}: отрицательная стоимость {cost}")
        in_date = _date(r.get("in_date", ""), w)
        if in_date and in_date > date.today():
            raise DataError(f"{w}: дата поступления в будущем: {in_date}")
        life = r.get("useful_life", "").strip()
        data.assets.append(Asset(
            asset_id=aid,
            inv_no=inv,
            name=r.get("name", "").strip(),
            category=_category(r.get("category", ""), w),
            in_date=in_date,
            cost=cost,
            counterparty=r.get("counterparty", "").strip(),
            useful_life=int(life) if life else None,
            is_legacy_pool=r.get("is_legacy_pool", "").strip() in ("1", "true", "yes"),
            note=r.get("note", "").strip(),
        ))

    for r in read_tsv(folder / "opening_balances.tsv"):
        w = _where(r)
        data.opening_balances.append(OpeningBalance(
            year=_int(r.get("year", ""), w),
            asset_id=r["asset_id"].strip(),
            category=_category(r.get("category", ""), w),
            residual=_dec(r.get("residual", ""), w),
            source=r.get("source", "onboarding").strip(),
            engine_version=r.get("engine_version", "").strip(),
            closed_at=r.get("closed_at", "").strip(),
        ))

    for r in read_tsv(folder / "disposals.tsv"):
        w = _where(r)
        typ = r.get("type", "").strip()
        if typ not in ("realizasiya", "leqv"):
            raise DataError(f"{w}: тип выбытия должен быть realizasiya|leqv, а не {typ!r}")
        data.disposals.append(Disposal(
            asset_id=r["asset_id"].strip(),
            date=_date(r.get("date", ""), w),
            type=typ,
            proceeds=_dec(r.get("proceeds", ""), w),
        ))

    for r in read_tsv(folder / "repairs.tsv"):
        w = _where(r)
        data.repairs.append(Repair(
            year=_int(r.get("year", ""), w),
            asset_id=r["asset_id"].strip(),
            date=_date(r.get("date", ""), w),
            amount=_dec(r.get("amount", ""), w),
            note=r.get("note", "").strip(),
        ))

    for r in read_tsv(folder / "taxpayer_status.tsv"):
        w = _where(r)
        st = r.get("status", "").strip()
        if st not in ("mikro", "kicik", "orta", "iri"):
            raise DataError(f"{w}: неизвестный статус {st!r}")
        data.statuses.append(TaxpayerStatus(
            year=_int(r.get("year", ""), w), status=st, basis=r.get("basis", "").strip(),
        ))

    for r in read_tsv(folder / "rate_elections.tsv"):
        w = _where(r)
        data.elections.append(RateElection(
            year=_int(r.get("year", ""), w),
            category=_category(r.get("category", ""), w),
            applied_rate=_dec(r.get("applied_rate", ""), w),
        ))

    for r in read_tsv(folder / "writeoffs.tsv"):
        w = _where(r)
        data.writeoffs.append(WriteOff(
            year=_int(r.get("year", ""), w),
            asset_id=r["asset_id"].strip(),
            reason=r.get("reason", "").strip(),
        ))

    known = {a.asset_id for a in data.assets}
    for coll, label in ((data.opening_balances, "opening_balances"),
                        (data.disposals, "disposals"),
                        (data.repairs, "repairs"),
                        (data.writeoffs, "writeoffs")):
        for row in coll:
            if row.asset_id not in known:
                raise DataError(f"{label}: ссылка на несуществующий asset_id {row.asset_id!r}")

    return data


def list_clients(root: Path) -> list[str]:
    base = root / "clients"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "config.toml").exists())


OPENING_HEADER = [
    "year", "asset_id", "category", "residual", "source", "engine_version", "closed_at",
]

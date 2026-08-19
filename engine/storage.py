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
    Addition, Asset, ClientData, Disposal, Group, OpeningBalance, RateElection,
    Repair, TaxpayerStatus, WriteOff,
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
        raise DataError(f"{where}: rəqəm deyil — {value!r}") from None


def _date(value: str, where: str) -> date | None:
    v = (value or "").strip()
    if v == "":
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise DataError(f"{where}: tarix YYYY-MM-DD formatında olmalıdır — {value!r}") from None


def _int(value: str, where: str) -> int:
    v = (value or "").strip()
    if v == "":
        raise DataError(f"{where}: tam ədəd boşdur")
    try:
        return int(v)
    except ValueError:
        raise DataError(f"{where}: tam ədəd deyil — {value!r}") from None


def check_qma(category: str, *, in_date, useful_life, is_legacy_pool,
              where: str = "") -> None:
    """What a QMA card must carry, checked on the way in AND on the way out.

    A straight line is a schedule, and a schedule needs two things a rate
    never did: where it starts and how long it runs. Both are therefore facts
    of the card rather than defaults the engine could supply --

    * `in_date` -- with no start there is no year zero, and the engine cannot
      tell a first year from a fifth;
    * the FİM on `qma-m` -- that IS what "istifadə müddəti məlum" means, so a
      card without it is not a known-term intangible, it is an unfinished one.

    The mirror check matters as much: a FİM written on `qma-n` says the term
    is known and unknown at once. Refused rather than ignored, because the
    figure it silently costs is large -- ten years against three.

    A group pool is refused outright: it stands for a category with no cards
    (§6.1), so it has neither a date nor a term, and 10% of a residual is the
    one thing a straight line will not do.

    Raising from both sides is deliberate (§8): the files are plain text and
    people edit them.
    """
    if CATEGORY_BY_CODE[category].kind != "qma":
        return
    w = f"{where}: " if where else ""
    name = CATEGORY_BY_CODE[category].name_az
    if is_legacy_pool:
        raise DataError(
            f"{w}qeyri-maddi aktiv üçün qrup qalığı tətbiq olunmur — "
            f"QMA hər kart üzrə ayrıca amortizasiya olunur (m.114.5)")
    if in_date is None:
        raise DataError(
            f"{w}{name}: alış tarixi tələb olunur — düz xətt metodu üçün "
            f"amortizasiya cədvəlinin başlanğıcı məlum olmalıdır")
    if category == "qma-m":
        if useful_life is None or int(useful_life) < 1:
            raise DataError(
                f"{w}{name}: istifadə müddəti (FİM, il) tələb olunur və 1-dən "
                f"kiçik ola bilməz (m.114.3.6)")
    elif useful_life is not None:
        raise DataError(
            f"{w}{name}: istifadə müddəti göstərilib — müddət məlumdursa, "
            f"kateqoriya «QMA — FİM məlum» olmalıdır")


def _category(value: str, where: str) -> str:
    v = (value or "").strip()
    if v not in CATEGORY_BY_CODE:
        raise DataError(
            f"{where}: naməlum kateqoriya {value!r}; "
            f"mümkün olanlar: {', '.join(CATEGORY_BY_CODE)}"
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
    """Atomic write: either the whole file lands or it is left untouched (§8).

    Written as UTF-8 WITH a BOM. Excel and Notepad on Windows have no other
    way to tell UTF-8 from the ANSI codepage, and guessing wrong turns every
    `ə ç ş ğ ı ö ü` into mojibake. Readers here use utf-8-sig, so the BOM
    never reaches the engine.
    """
    body = ["\t".join(header)]
    for r in rows:
        body.append("\t".join("" if c is None else str(c) for c in r))
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="\n", delete=False, dir=str(path.parent)
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
    # The owner's norms live next to the engine, not in the client folder
    # (§5.1), so they have to be re-read somewhere. This is the one place both
    # the web UI and the CLI pass through. Without it `ev.py calc` ignored
    # rates.tsv entirely and answered differently than the same year on
    # screen -- silently, which is the failure mode §2.1 exists to prevent.
    from . import rates as _rates
    try:
        _rates.refresh(root)
    except (ValueError, KeyError, InvalidOperation) as e:
        raise DataError(f"normalar faylı oxunmadı: {e}") from None

    folder = root / "clients" / slug
    if not folder.is_dir():
        raise DataError(f"müştəri tapılmadı: {folder}")

    cfg_path = folder / "config.toml"
    if not cfg_path.exists():
        raise DataError(f"{folder} qovluğunda config.toml yoxdur")
    cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8-sig"))

    data = ClientData(
        slug=slug,
        client_name=cfg.get("client_name", slug),
        voen=str(cfg.get("voen", "")),
        start_year=int(cfg.get("start_year", 0)),
        format_version=int(cfg.get("format_version", 1)),
        client_id=str(cfg.get("client_id", "")).strip(),
    )

    # Read before the assets, because an asset points at one. A group is
    # reporting only -- it never reaches a figure (§13.1) -- but a card
    # pointing at a group that is not there is still a broken store, and the
    # store says so at READ time rather than showing a blank column later.
    seen_groups: set[str] = set()
    seen_group_names: set[str] = set()
    for r in read_tsv(folder / "groups.tsv"):
        w = _where(r)
        gid = r.get("group_id", "").strip()
        name = r.get("name", "").strip()
        if not gid:
            raise DataError(f"{w}: group_id boşdur")
        if gid in seen_groups:
            raise DataError(f"{w}: group_id təkrarlanır — {gid!r}")
        if not name:
            raise DataError(f"{w}: qrup adı boşdur")
        # Case-folded, because the point of a dictionary is that "Serverlər"
        # cannot become two groups (§13.1).
        if name.casefold() in seen_group_names:
            raise DataError(f"{w}: qrup adı təkrarlanır — {name!r}")
        seen_groups.add(gid)
        seen_group_names.add(name.casefold())
        data.groups.append(Group(group_id=gid, name=name,
                                 note=r.get("note", "").strip()))

    seen_ids: set[str] = set()
    seen_inv: set[str] = set()
    for r in read_tsv(folder / "assets.tsv"):
        w = _where(r)
        aid = r["asset_id"].strip()
        if not aid:
            raise DataError(f"{w}: asset_id boşdur")
        if aid in seen_ids:
            raise DataError(f"{w}: asset_id təkrarlanır — {aid!r}")
        seen_ids.add(aid)
        inv = r.get("inv_no", "").strip()
        if inv:
            if inv in seen_inv:
                raise DataError(f"{w}: inv_no təkrarlanır — {inv!r}")
            seen_inv.add(inv)
        cost = _dec(r.get("cost", ""), w)
        if cost < 0:
            raise DataError(f"{w}: ilkin dəyər mənfidir — {cost}")
        in_date = _date(r.get("in_date", ""), w)
        if in_date and in_date > date.today():
            raise DataError(f"{w}: alış tarixi gələcəkdədir — {in_date}")
        life = r.get("useful_life", "").strip()
        gid = r.get("group_id", "").strip()
        if gid and gid not in seen_groups:
            raise DataError(f"{w}: mövcud olmayan qrupa istinad — {gid!r}")
        cat = _category(r.get("category", ""), w)
        is_pool = r.get("is_legacy_pool", "").strip() in ("1", "true", "yes")
        check_qma(cat, in_date=in_date,
                  useful_life=int(life) if life else None,
                  is_legacy_pool=is_pool, where=w)
        data.assets.append(Asset(
            asset_id=aid,
            inv_no=inv,
            name=r.get("name", "").strip(),
            category=cat,
            in_date=in_date,
            cost=cost,
            counterparty=r.get("counterparty", "").strip(),
            e_qaime=r.get("e_qaime", "").strip(),
            serial_no=r.get("serial_no", "").strip(),
            group_id=gid,
            useful_life=int(life) if life else None,
            is_legacy_pool=is_pool,
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
            raise DataError(f"{w}: xaricetmə növü realizasiya|leqv olmalıdır, {typ!r} deyil")
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

    for r in read_tsv(folder / "additions.tsv"):
        w = _where(r)
        data.additions.append(Addition(
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
            raise DataError(f"{w}: naməlum status {st!r}")
        use = r.get("use_coefficient", "").strip().lower()
        data.statuses.append(TaxpayerStatus(
            year=_int(r.get("year", ""), w), status=st,
            basis=r.get("basis", "").strip(),
            # absent column means "take it": that was the behaviour before the
            # waiver existed, and old files must keep computing the same way
            use_coefficient=use not in ("0", "false", "no", "yox"),
        ))

    for r in read_tsv(folder / "rate_elections.tsv"):
        w = _where(r)
        data.elections.append(RateElection(
            year=_int(r.get("year", ""), w),
            category=_category(r.get("category", ""), w),
            applied_rate=_dec(r.get("applied_rate", ""), w),
            asset_id=r.get("asset_id", "").strip(),
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
                        (data.additions, "additions"),
                        (data.writeoffs, "writeoffs")):
        for row in coll:
            if row.asset_id not in known:
                raise DataError(f"{label}: mövcud olmayan asset_id-yə istinad — {row.asset_id!r}")
    for e in data.elections:
        if e.asset_id and e.asset_id not in known:
            raise DataError(
                f"rate_elections: mövcud olmayan asset_id-yə istinad — {e.asset_id!r}")
        if e.asset_id:
            asset = next(a for a in data.assets if a.asset_id == e.asset_id)
            if asset.category != e.category:
                raise DataError(
                    f"rate_elections: {e.asset_id} {asset.category!r} kateqoriyasına "
                    f"aiddir, sətirdə isə {e.category!r} göstərilib")

    return data


def list_clients(root: Path) -> list[str]:
    base = root / "clients"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "config.toml").exists())


OPENING_HEADER = [
    "year", "asset_id", "category", "residual", "source", "engine_version", "closed_at",
]

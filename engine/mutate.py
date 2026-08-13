"""Writing to a client folder (CLAUDE.md §8).

Every change goes through `transaction`, which does four things in order:

    1. backs the folder up,
    2. applies the change with atomic per-file writes,
    3. re-reads and re-validates the WHOLE store,
    4. rolls back to the backup if step 3 fails.

Step 3 is the point. Individual field checks cannot catch cross-file damage --
deleting an asset that a balance still points at, for instance -- so instead of
trying to enumerate those cases the store is simply re-parsed after each
change. If it no longer loads, the change never happened.
"""

from __future__ import annotations

import getpass
import shutil
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from .calc import compute_year
from .rates import CATEGORY_BY_CODE
from .storage import DataError, load_client, read_tsv, write_tsv

D = Decimal

HEADERS: dict[str, list[str]] = {
    "assets.tsv": ["asset_id", "inv_no", "name", "category", "in_date", "cost",
                   "counterparty", "useful_life", "is_legacy_pool", "note"],
    "opening_balances.tsv": ["year", "asset_id", "category", "residual", "source",
                             "engine_version", "closed_at"],
    "disposals.tsv": ["asset_id", "date", "type", "proceeds"],
    "repairs.tsv": ["year", "asset_id", "date", "amount", "note"],
    "taxpayer_status.tsv": ["year", "status", "basis"],
    "rate_elections.tsv": ["year", "category", "applied_rate", "asset_id"],
    "writeoffs.tsv": ["year", "asset_id", "reason"],
    "changelog.tsv": ["timestamp", "user", "action", "asset_id", "field",
                      "old_value", "new_value"],
}


def folder(root: Path, slug: str) -> Path:
    f = root / "clients" / slug
    if not f.is_dir():
        raise DataError(f"клиент не найден: {slug}")
    return f


def rows_of(root: Path, slug: str, name: str) -> list[dict[str, str]]:
    header = HEADERS[name]
    out = []
    for r in read_tsv(folder(root, slug) / name):
        out.append({h: r.get(h, "") for h in header})
    return out


def save_rows(root: Path, slug: str, name: str, rows: list[dict[str, str]]) -> None:
    header = HEADERS[name]
    write_tsv(folder(root, slug) / name,
              header, [[r.get(h, "") for h in header] for r in rows])


# ------------------------------------------------------------- transaction ---

class Tx:
    def __init__(self, root: Path, slug: str, action: str):
        self.root, self.slug, self.action = root, slug, action
        self.entries: list[list[str]] = []

    def log(self, asset_id: str = "", field: str = "",
            old: Any = "", new: Any = "") -> None:
        self.entries.append([
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            getpass.getuser(), self.action, asset_id, field, str(old), str(new),
        ])


@contextmanager
def transaction(root: Path, slug: str, action: str) -> Iterator[Tx]:
    src = folder(root, slug)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = root / "backups" / slug / stamp
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)

    tx = Tx(root, slug, action)
    try:
        yield tx
        # The store must still parse AND still compute. Parsing alone is not
        # enough: an election above the ceiling reads back fine but breaks
        # every report until someone edits the file by hand.
        data = load_client(root, slug)
        closed = data.closed_years()
        for st in data.statuses:
            if st.year not in closed:
                compute_year(data, st.year)
    except BaseException:
        for item in src.iterdir():       # roll back to the backup
            if item.is_file():
                item.unlink()
        for item in dest.iterdir():
            shutil.copy2(item, src / item.name)
        raise

    if tx.entries:
        path = src / "changelog.tsv"
        existing = read_tsv(path)
        header = HEADERS["changelog.tsv"]
        out = [[r.get(h, "") for h in header] for r in existing]
        out.extend(tx.entries)
        write_tsv(path, header, out)


# ---------------------------------------------------------------- checking ---

def guard_open_year(root: Path, slug: str, year: int) -> None:
    """Closed years are sealed: their return has been filed (§6)."""
    if year in load_client(root, slug).closed_years():
        raise DataError(
            f"{year} ili bağlıdır — bəyannamə təqdim edilib, dəyişiklik qəbul "
            f"edilmir (CLAUDE.md §6)"
        )


def dec(value: Any, field: str, *, allow_zero: bool = True) -> str:
    try:
        d = D(str(value).replace(",", ".").strip() or "0")
    except InvalidOperation:
        raise DataError(f"{field}: rəqəm deyil — {value!r}") from None
    if d < 0 or (not allow_zero and d == 0):
        raise DataError(f"{field}: mənfi və ya sıfır ola bilməz — {d}")
    return f"{d:.2f}"


def iso_date(value: Any, field: str, *, required: bool = True) -> str:
    v = str(value or "").strip()
    if not v:
        if required:
            raise DataError(f"{field}: tarix tələb olunur")
        return ""
    try:
        d = datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise DataError(f"{field}: tarix YYYY-MM-DD formatında olmalıdır") from None
    if d > date.today():
        raise DataError(f"{field}: gələcək tarix ola bilməz — {d}")
    return d.isoformat()


def category_of(value: Any, field: str = "category") -> str:
    v = str(value or "").strip()
    if v not in CATEGORY_BY_CODE:
        raise DataError(f"{field}: naməlum kateqoriya {v!r}")
    return v


def next_asset_id(rows: list[dict[str, str]]) -> str:
    n = 0
    for r in rows:
        aid = r.get("asset_id", "")
        if aid.startswith("AV-") and aid[3:].isdigit():
            n = max(n, int(aid[3:]))
    return f"AV-{n + 1:03d}"


# ----------------------------------------------------------------- actions ---

MODES = ("new", "carried", "pool")


def create_asset(root: Path, slug: str, p: dict) -> str:
    """Three ways an asset enters the books.

    `new`      bought during the open year -- date and cost are known.
    `carried`  already on the books when the client arrived; the opening
               residual comes from their last filed return. Initial cost may
               be unknown, in which case only the 500 AZN half of the
               threshold test can ever apply to it.
    `pool`     the client could only give GROUP totals, not a breakdown per
               asset. One card per category carries the group residual
               (§6.1). No inventory number, no date, no initial cost.
    """
    mode = str(p.get("mode", "new"))
    if mode not in MODES:
        raise DataError(f"naməlum rejim: {mode!r}")
    category = category_of(p.get("category"))
    residual = str(p.get("opening_residual", "")).strip()

    with transaction(root, slug, "asset.create") as tx:
        assets = rows_of(root, slug, "assets.tsv")
        inv = str(p.get("inv_no", "")).strip()
        if inv and any(r["inv_no"] == inv for r in assets):
            raise DataError(f"inv_no {inv!r} artıq mövcuddur")

        if mode == "pool":
            name = str(p.get("name", "")).strip() or \
                f"{CATEGORY_BY_CODE[category].name_az} — qrup qalığı"
            inv, in_date, cost = "", "", "0.00"
            if not residual:
                raise DataError("Qrup qalığı üçün qalıq dəyər tələb olunur")
        else:
            name = str(p.get("name", "")).strip()
            if not name:
                raise DataError("Adı boş ola bilməz")
            in_date = iso_date(p.get("in_date"), "Alış tarixi",
                               required=(mode == "new"))
            cost = dec(p.get("cost"), "İlkin dəyər",
                       allow_zero=(mode == "carried"))
            if mode == "new" and D(cost) == 0:
                raise DataError("İlkin dəyər sıfır ola bilməz")
            if mode == "carried" and not residual:
                raise DataError("Əvvəlki illərdən gələn ƏV üçün qalıq dəyər "
                                "tələb olunur")

        aid = next_asset_id(assets)
        assets.append({
            "asset_id": aid, "inv_no": inv, "name": name, "category": category,
            "in_date": in_date, "cost": cost,
            "counterparty": str(p.get("counterparty", "")).strip(),
            "useful_life": str(p.get("useful_life", "")).strip(),
            "is_legacy_pool": "1" if mode == "pool" else "",
            "note": str(p.get("note", "")).strip(),
        })
        save_rows(root, slug, "assets.tsv", assets)
        tx.log(aid, "asset", "", f"[{mode}] {inv} {name}".strip())

        if residual:
            year = int(p["opening_year"])
            guard_open_year(root, slug, year)
            ob = rows_of(root, slug, "opening_balances.tsv")
            ob.append({
                "year": str(year), "asset_id": aid, "category": category,
                "residual": dec(residual, "Qalıq dəyər"),
                "source": "onboarding", "engine_version": "", "closed_at": "",
            })
            save_rows(root, slug, "opening_balances.tsv", ob)
            tx.log(aid, f"opening_balance {year}", "", residual)
    return aid


def update_asset(root: Path, slug: str, p: dict) -> str:
    aid = str(p["asset_id"])
    with transaction(root, slug, "asset.update") as tx:
        assets = rows_of(root, slug, "assets.tsv")
        row = next((r for r in assets if r["asset_id"] == aid), None)
        if row is None:
            raise DataError(f"ƏV tapılmadı: {aid}")
        new = {
            "inv_no": str(p.get("inv_no", "")).strip(),
            "name": str(p.get("name", "")).strip(),
            "category": category_of(p.get("category")),
            "in_date": iso_date(p.get("in_date"), "Alış tarixi"),
            "cost": dec(p.get("cost"), "İlkin dəyər"),
            "counterparty": str(p.get("counterparty", "")).strip(),
            "note": str(p.get("note", "")).strip(),
        }
        if new["inv_no"] and any(
                r["inv_no"] == new["inv_no"] and r["asset_id"] != aid for r in assets):
            raise DataError(f"inv_no {new['inv_no']!r} artıq mövcuddur")
        if not new["name"]:
            raise DataError("Adı boş ola bilməz")
        for field, value in new.items():
            if row[field] != value:
                tx.log(aid, field, row[field], value)
                row[field] = value
        save_rows(root, slug, "assets.tsv", assets)

        # The category lives on the balance rows too; keep them in step.
        ob = rows_of(root, slug, "opening_balances.tsv")
        for r in ob:
            if r["asset_id"] == aid and r["category"] != new["category"]:
                r["category"] = new["category"]
        save_rows(root, slug, "opening_balances.tsv", ob)
    return aid


def delete_asset(root: Path, slug: str, p: dict) -> str:
    """Delete the asset AND everything that references it.

    Removing only the card is what left an orphaned opening balance behind
    when the files were edited by hand.
    """
    aid = str(p["asset_id"])
    with transaction(root, slug, "asset.delete") as tx:
        for name in ("opening_balances.tsv", "disposals.tsv", "repairs.tsv",
                     "writeoffs.tsv", "rate_elections.tsv"):
            rows = rows_of(root, slug, name)
            kept = [r for r in rows if r.get("asset_id") != aid]
            if len(kept) != len(rows):
                tx.log(aid, name, f"{len(rows) - len(kept)} sətir", "silindi")
                save_rows(root, slug, name, kept)
        assets = rows_of(root, slug, "assets.tsv")
        row = next((r for r in assets if r["asset_id"] == aid), None)
        if row is None:
            raise DataError(f"ƏV tapılmadı: {aid}")
        tx.log(aid, "asset", f"{row['inv_no']} {row['name']}", "silindi")
        save_rows(root, slug, "assets.tsv",
                  [r for r in assets if r["asset_id"] != aid])
    return aid


def set_opening(root: Path, slug: str, p: dict) -> str:
    aid, year = str(p["asset_id"]), int(p["year"])
    with transaction(root, slug, "opening.set") as tx:
        guard_open_year(root, slug, year)
        assets = rows_of(root, slug, "assets.tsv")
        asset = next((r for r in assets if r["asset_id"] == aid), None)
        if asset is None:
            raise DataError(f"ƏV tapılmadı: {aid}")
        rows = rows_of(root, slug, "opening_balances.tsv")
        value = str(p.get("residual", "")).strip()
        old = next((r for r in rows
                    if r["asset_id"] == aid and r["year"] == str(year)), None)
        if value == "":
            if old:
                rows.remove(old)
                tx.log(aid, f"opening_balance {year}", old["residual"], "silindi")
        elif old:
            v = dec(value, "Qalıq dəyər")
            if old["residual"] != v:
                tx.log(aid, f"opening_balance {year}", old["residual"], v)
                old["residual"] = v
        else:
            v = dec(value, "Qalıq dəyər")
            rows.append({"year": str(year), "asset_id": aid,
                         "category": asset["category"], "residual": v,
                         "source": "onboarding", "engine_version": "", "closed_at": ""})
            tx.log(aid, f"opening_balance {year}", "", v)
        save_rows(root, slug, "opening_balances.tsv", rows)
    return aid


def set_disposal(root: Path, slug: str, p: dict) -> str:
    aid = str(p["asset_id"])
    with transaction(root, slug, "disposal.set") as tx:
        rows = rows_of(root, slug, "disposals.tsv")
        rows = [r for r in rows if r["asset_id"] != aid]
        if not p.get("remove"):
            when = iso_date(p.get("date"), "Xaricetmə tarixi")
            guard_open_year(root, slug, int(when[:4]))
            typ = str(p.get("type", "")).strip()
            if typ not in ("realizasiya", "leqv"):
                raise DataError("Xaricetmə növü: realizasiya | leqv")
            rows.append({"asset_id": aid, "date": when, "type": typ,
                         "proceeds": dec(p.get("proceeds"), "Satış məbləği")})
            tx.log(aid, "disposal", "", f"{when} {typ}")
        else:
            tx.log(aid, "disposal", "var", "silindi")
        save_rows(root, slug, "disposals.tsv", rows)
    return aid


def add_repair(root: Path, slug: str, p: dict) -> str:
    aid = str(p["asset_id"])
    with transaction(root, slug, "repair.add") as tx:
        when = iso_date(p.get("date"), "Təmir tarixi")
        year = int(when[:4])
        guard_open_year(root, slug, year)
        amount = dec(p.get("amount"), "Məbləğ", allow_zero=False)
        rows = rows_of(root, slug, "repairs.tsv")
        rows.append({"year": str(year), "asset_id": aid, "date": when,
                     "amount": amount, "note": str(p.get("note", "")).strip()})
        save_rows(root, slug, "repairs.tsv", rows)
        tx.log(aid, f"repair {when}", "", amount)
    return aid


def remove_repair(root: Path, slug: str, p: dict) -> str:
    aid, when = str(p["asset_id"]), str(p["date"])
    with transaction(root, slug, "repair.remove") as tx:
        guard_open_year(root, slug, int(when[:4]))
        rows = rows_of(root, slug, "repairs.tsv")
        kept = [r for r in rows if not (r["asset_id"] == aid and r["date"] == when)]
        tx.log(aid, f"repair {when}", "var", "silindi")
        save_rows(root, slug, "repairs.tsv", kept)
    return aid


def set_writeoff(root: Path, slug: str, p: dict) -> str:
    """Record (or withdraw) the decision to write an asset off under 500/5%."""
    aid, year = str(p["asset_id"]), int(p["year"])
    with transaction(root, slug, "writeoff.set") as tx:
        guard_open_year(root, slug, year)
        rows = rows_of(root, slug, "writeoffs.tsv")
        rows = [r for r in rows
                if not (r["asset_id"] == aid and r["year"] == str(year))]
        if p.get("enabled"):
            reason = str(p.get("reason", "")).strip() or \
                "VM m.114 — 500/5% həddi, birdəfəlik silinmə"
            rows.append({"year": str(year), "asset_id": aid, "reason": reason})
            tx.log(aid, f"writeoff {year}", "", reason)
        else:
            tx.log(aid, f"writeoff {year}", "var", "silindi")
        save_rows(root, slug, "writeoffs.tsv", rows)
    return aid


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


def set_status(root: Path, slug: str, p: dict) -> str:
    year = int(p["year"])
    status = str(p.get("status", "")).strip()
    if status not in ("mikro", "kicik", "orta", "iri"):
        raise DataError("Status: mikro | kicik | orta | iri")
    with transaction(root, slug, "status.set") as tx:
        guard_open_year(root, slug, year)
        rows = rows_of(root, slug, "taxpayer_status.tsv")
        old = next((r for r in rows if r["year"] == str(year)), None)
        if old:
            tx.log("", f"status {year}", old["status"], status)
            old["status"] = status
            old["basis"] = str(p.get("basis", old.get("basis", ""))).strip()
        else:
            rows.append({"year": str(year), "status": status,
                         "basis": str(p.get("basis", "")).strip()})
            tx.log("", f"status {year}", "", status)
        save_rows(root, slug, "taxpayer_status.tsv", rows)
    return status


ACTIONS = {
    "asset.create": create_asset,
    "asset.update": update_asset,
    "asset.delete": delete_asset,
    "opening.set": set_opening,
    "disposal.set": set_disposal,
    "repair.add": add_repair,
    "repair.remove": remove_repair,
    "writeoff.set": set_writeoff,
    "election.set": set_election,
    "status.set": set_status,
}

"""Bulk import from someone else's workbook (§11.2).

The columns are guessed, the user corrects the guess, and the whole thing is
validated through the real write path with `dry_run` so the preview cannot
disagree with the import."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from ..rates import CATEGORY_BY_CODE
from ..storage import DataError, check_qma

from .assets import life_of
from .core import guard_open_year, rows_of, save_rows, transaction
from .groups import find_group, next_group_id
from .numbering import next_asset_id, suggest_inv_no
from .parse import _fold, _fold2, category_of, dec, iso_date

class _DryRun(Exception):
    """Raised to force the transaction to roll back after a validation pass."""


def resolve_group(groups: list[dict[str, str]], name) -> str:
    """A group name from someone else's sheet into our group_id.

    Matched case- and space-insensitively so «Serverlər» and «serverler» land
    in one group rather than two (§13.1); unknown names are added to the
    dictionary, which is the only way a bulk import can carry a grouping at
    all. Appends to `groups` in place -- the caller saves it inside the same
    transaction, so a rolled-back import leaves no orphan groups behind.
    """
    clean = " ".join(str(name or "").split())
    if not clean:
        return ""
    hit = find_group(groups, clean)
    if hit:
        return hit["group_id"]
    gid = next_group_id(groups)
    groups.append({"group_id": gid, "name": clean, "note": ""})
    return gid


IMPORT_FIELDS = ("inv_no", "name", "category", "in_date", "cost",
                 "opening_residual", "counterparty", "e_qaime", "serial_no",
                 "group", "useful_life", "note")

# Header names seen in the wild: the source workbook, 1C exports, and the
# obvious Russian/English equivalents. Matching is case- and space-insensitive.
IMPORT_ALIASES = {
    "inv_no": ["inv", "inv.№", "inv №", "inv no", "invno", "inventar",
               "inventar nömrəsi", "nömrə", "nomre", "№", "kod nömrə",
               "инв", "инв.№", "инв №", "инвентарный номер", "номер"],
    "name": ["ad", "adı", "adi", "name", "наименование", "название", "ос"],
    "category": ["kod", "kateqoriya", "категория", "код", "group", "qrup"],
    "in_date": ["alış tarixi", "alis tarixi", "tarix", "дата", "дата приобретения",
                "date", "in_date"],
    "cost": ["ilkin dəyər", "ilkin deyer", "первоначальная стоимость",
             "первоначальная", "cost", "dəyər", "alış qiyməti", "qiymət",
             "стоимость", "цена"],
    "opening_residual": ["qalıq dəyər", "qaliq deyer", "qalıq", "остаточная стоимость",
                         "остаток", "residual", "qalıq (il əvvəli)"],
    "counterparty": ["kontragent", "контрагент", "təchizatçı", "поставщик", "supplier"],
    "e_qaime": ["e-qaimə", "e qaimə", "eqaime", "qaimə", "qaime", "e-qaime",
                "hesab-faktura", "faktura", "накладная", "э-накладная",
                "счёт-фактура", "счет-фактура", "invoice"],
    "serial_no": ["seriya nömrəsi", "seriya", "serial", "serial no", "serial number",
                  "s/n", "sn", "vin", "zavod nömrəsi", "заводской номер",
                  "серийный номер", "серийный", "серия"],
    # The client's own classification arrives as a NAME, because that is what
    # their sheet holds; the id is ours and is resolved on the way in.
    #
    # Deliberately NOT "qrup" or "group" on their own: `category` has claimed
    # both since before this field existed -- a column headed «Qrup» is far
    # more often the tax group -- and taking them back would silently move an
    # existing client's category column into a reporting field that changes
    # no figure. Losing the tax category is the expensive half of that trade.
    "group": ["növ", "növü", "nov", "qrup adı", "qrup adi", "group name",
              "тип", "вид", "növ (qrup)"],
    # Only a QMA with a known term uses it (m.114.3.6). Left out of a
    # client's sheet it is simply empty, like the serial next to it.
    "useful_life": ["fim", "istifadə müddəti", "istifade muddeti", "müddət",
                    "muddet", "faydalı istifadə müddəti", "срок",
                    "срок использования", "срок полезного использования",
                    "useful life", "life"],
    "note": ["qeyd", "примечание", "note", "комментарий"],
}

def guess_columns(header: list[str]) -> dict[str, int]:
    """Best-effort mapping of source columns to our fields. The user corrects
    it in the UI; guessing only removes the boring part.

    Exact matches are claimed before loose ones, and that ordering is load-
    bearing rather than tidy. Matching is substring-based, so a short alias
    swallows a longer header that happens to contain it: `inv_no` lists
    "nömrə", "Seriya nömrəsi" contains it, and `inv_no` is declared first --
    so the serial column was being imported as the inventory number. Whichever
    field is written first in IMPORT_ALIASES should not decide that.
    """
    norm = [_fold(h) for h in header]
    norm2 = [_fold2(h) for h in header]
    folded = {f: {_fold(a) for a in aliases} | {_fold2(a) for a in aliases}
              for f, aliases in IMPORT_ALIASES.items()}
    out: dict[str, int] = {}
    taken: set[int] = set()

    def claim(field: str, i: int) -> None:
        out[field] = i
        taken.add(i)

    for exact in (True, False):
        for field, aliases in folded.items():
            if field in out:
                continue
            for i, (h, h2) in enumerate(zip(norm, norm2)):
                if i in taken or not h:
                    continue
                hit = (h in aliases or h2 in aliases) if exact else any(
                    a and (x.startswith(a) or a in x)
                    for a in aliases for x in (h, h2))
                if hit:
                    claim(field, i)
                    break
    return out


def import_assets(root: Path, slug: str, p: dict) -> Any:
    """Bulk import. `dry_run` validates through the exact same path and then
    rolls back, so the preview cannot disagree with the real import."""
    rows = p.get("rows") or []
    year = int(p.get("opening_year") or 0)
    dry = bool(p.get("dry_run"))
    report: dict[str, Any] = {"created": 0, "errors": [], "rows": []}

    try:
        with transaction(root, slug, "asset.import") as tx:
            assets = rows_of(root, slug, "assets.tsv")
            # Import APPENDS -- always has. Said out loud in the preview,
            # because the second import of a corrected sheet is the normal
            # thing to try, and with inventory numbers left blank there is
            # nothing to collide and nothing to warn: the duplicates simply
            # arrive under fresh numbers.
            report["existing"] = len(assets)
            ob = rows_of(root, slug, "opening_balances.tsv")
            groups = rows_of(root, slug, "groups.tsv")
            before = len(groups)
            seen_inv = {r["inv_no"] for r in assets if r["inv_no"]}

            for n, raw in enumerate(rows, start=1):
                try:
                    inv = str(raw.get("inv_no", "")).strip()
                    name = str(raw.get("name", "")).strip()
                    if not name and not inv:
                        continue                       # blank line, skip quietly
                    if not name:
                        raise DataError("Adı boş")
                    if inv and inv in seen_inv:
                        raise DataError(f"inv_no {inv!r} təkrarlanır")
                    category = category_of(raw.get("category"))
                    # Excluded from bulk import on purpose, not by omission:
                    # m.115.6-1 requires confirming per repair that it was
                    # neither reimbursed by the lessor nor offset against rent
                    # (m.115.6), and a spreadsheet row has nowhere to carry
                    # that confirmation. One card per repair-year is also a
                    # low-volume fact, entered through "+ Yeni ƏV" where the
                    # confirmation lives (mutate.assets.create_asset).
                    if category == "it":
                        raise DataError(
                            f"{CATEGORY_BY_CODE[category].name_az}: idxal "
                            f"vasitəsilə əlavə edilmir — «+ Yeni ƏV» "
                            f"formasından, hər təmir ili üçün ayrıca kart "
                            f"yaradın (m.115.6-1)."
                        )
                    if not inv:
                        inv = suggest_inv_no(assets, category)
                        auto_inv = True
                    else:
                        auto_inv = False
                    residual = str(raw.get("opening_residual", "")).strip()
                    cost_raw = str(raw.get("cost", "")).strip()
                    in_date = iso_date(raw.get("in_date"), "Alış tarixi",
                                       required=False)
                    mode = "carried" if residual else "new"
                    if mode == "new" and not cost_raw:
                        raise DataError("nə ilkin dəyər, nə qalıq dəyər var")
                    cost = dec(cost_raw or "0", "İlkin dəyər")
                    if mode == "new" and not in_date:
                        raise DataError("Alış tarixi tələb olunur")

                    # A name that is not in the dictionary yet creates the
                    # group -- the client's sheet is where these names come
                    # from, and refusing the import over a spelling would be
                    # asking the accountant to key the list in twice. The
                    # preview says how many will be created before anything is
                    # written.
                    # A term arriving from the sheet goes through the same
                    # check as one typed into the form: whether it is required,
                    # forbidden or ignored depends on the category, and an
                    # import that quietly disagreed with the form would be the
                    # worse of the two paths to trust (§11.2).
                    life = life_of(raw.get("useful_life"))
                    life_str = "" if life is None else str(life)
                    check_qma(category, in_date=in_date or None,
                              useful_life=life, is_legacy_pool=False)
                    gid = resolve_group(groups, raw.get("group"))
                    aid = next_asset_id(assets)
                    assets.append({
                        "asset_id": aid, "inv_no": inv, "name": name,
                        "category": category, "in_date": in_date, "cost": cost,
                        "counterparty": str(raw.get("counterparty", "")).strip(),
                        "useful_life": life_str, "is_legacy_pool": "",
                        "note": str(raw.get("note", "")).strip(),
                        "e_qaime": str(raw.get("e_qaime", "")).strip(),
                        "serial_no": str(raw.get("serial_no", "")).strip(),
                        "group_id": gid,
                    })
                    if inv:
                        seen_inv.add(inv)
                    residual_norm = ""
                    if residual:
                        if not year:
                            raise DataError("qalıq dəyər üçün il göstərilməyib")
                        residual_norm = dec(residual, "Qalıq dəyər")
                        ob.append({
                            "year": str(year), "asset_id": aid, "category": category,
                            "residual": residual_norm,
                            "source": "onboarding", "engine_version": "",
                            "closed_at": "",
                        })
                    report["created"] += 1
                    # Report the NORMALISED numbers: the preview must show the
                    # value that will actually be stored, not the raw cell.
                    report["rows"].append({"line": n, "asset_id": aid, "inv_no": inv,
                                           "auto_inv": auto_inv,
                                           "name": name, "category": category,
                                           "cost": cost, "residual": residual_norm,
                                           "in_date": in_date, "mode": mode,
                                           "ok": True})
                except DataError as e:
                    report["errors"].append({"line": n, "message": str(e)})
                    report["rows"].append({"line": n, "inv_no": raw.get("inv_no", ""),
                                           "name": raw.get("name", ""), "ok": False,
                                           "message": str(e)})

            if report["errors"]:
                raise DataError(
                    f"{len(report['errors'])} sətirdə xəta var — heç nə yazılmadı. "
                    f"Import ya bütövlükdə keçir, ya da heç keçmir."
                )
            if year:
                guard_open_year(root, slug, year)
            report["groups_created"] = len(groups) - before
            if len(groups) != before:
                save_rows(root, slug, "groups.tsv", groups)
            save_rows(root, slug, "assets.tsv", assets)
            save_rows(root, slug, "opening_balances.tsv", ob)
            tx.log("", "import", "", f"{report['created']} ƏV")
            if dry:
                raise _DryRun
    except _DryRun:
        report["dry_run"] = True
    except DataError:
        if not dry:
            raise
        report["dry_run"] = True
    return report


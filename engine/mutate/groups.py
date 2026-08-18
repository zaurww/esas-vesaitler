"""The client's own grouping inside a tax category (§13.1).

A group is a reporting dimension and nothing else: it never carries a rate, a
repair limit or a figure of any kind. The moment it did, it would be a
substitute category and the aggregation by art. 114/115 would stop being
universal -- which is exactly what the fixed category enum in §4 protects.

So everything here is bookkeeping about names: create one, rename it, delete
it, put cards into it. No calculation reads any of it."""

from __future__ import annotations

from pathlib import Path

from ..storage import DataError

from .core import rows_of, save_rows, transaction

GROUP_ID_FMT = "QR-{:03d}"


def next_group_id(rows: list[dict[str, str]]) -> str:
    n = 0
    for r in rows:
        gid = r.get("group_id", "")
        if gid.startswith("QR-") and gid[3:].isdigit():
            n = max(n, int(gid[3:]))
    return GROUP_ID_FMT.format(n + 1)


def find_group(rows: list[dict[str, str]], name: str) -> dict[str, str] | None:
    """A group by name, case- and space-insensitively.

    The whole point of keeping a dictionary is that «Serverlər» typed twice is
    one group, so matching has to be as forgiving as the typing is (§2.1: a
    silently split report is worse than none).
    """
    key = " ".join(str(name or "").split()).casefold()
    return next((r for r in rows
                 if " ".join(r["name"].split()).casefold() == key), None)


def group_ref(root: Path, slug: str, value) -> str:
    """Validate a group_id coming in from a form. Empty means "no group".

    Checked at the door as well as at read time (§8): the recompute after a
    write would catch a dangling reference anyway, but only by rolling the
    whole action back with a message about the store, not about the field the
    user just filled in.
    """
    gid = str(value or "").strip()
    if not gid:
        return ""
    if not any(r["group_id"] == gid for r in rows_of(root, slug, "groups.tsv")):
        raise DataError(f"növ tapılmadı: {gid}")
    return gid


def _clean_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise DataError("Növün adı boş ola bilməz")
    return name


def create_group(root: Path, slug: str, p: dict) -> str:
    with transaction(root, slug, "group.create") as tx:
        groups = rows_of(root, slug, "groups.tsv")
        name = _clean_name(p.get("name"))
        hit = find_group(groups, name)
        if hit:
            raise DataError(f"«{hit['name']}» növü artıq mövcuddur")
        gid = next_group_id(groups)
        groups.append({"group_id": gid, "name": name,
                       "note": str(p.get("note", "")).strip()})
        save_rows(root, slug, "groups.tsv", groups)
        tx.log("", "group", "", f"{gid} {name}")
    return gid


def update_group(root: Path, slug: str, p: dict) -> str:
    """Rename a group. One edit here instead of one per card -- the reason the
    card stores `group_id` and not the name (§4, the inv_no reasoning)."""
    gid = str(p.get("group_id", "")).strip()
    with transaction(root, slug, "group.update") as tx:
        groups = rows_of(root, slug, "groups.tsv")
        row = next((r for r in groups if r["group_id"] == gid), None)
        if row is None:
            raise DataError(f"növ tapılmadı: {gid}")
        name = _clean_name(p.get("name"))
        hit = find_group(groups, name)
        if hit and hit["group_id"] != gid:
            raise DataError(f"«{hit['name']}» növü artıq mövcuddur")
        note = str(p.get("note", "")).strip()
        for field, value in (("name", name), ("note", note)):
            if row[field] != value:
                tx.log("", f"group.{field}", row[field], value)
                row[field] = value
        save_rows(root, slug, "groups.tsv", groups)
    return gid


def delete_group(root: Path, slug: str, p: dict) -> str:
    """Refused while cards still point at it.

    Clearing forty cards as a side effect of one click is data loss that looks
    like tidying up: the group is gone, the cards silently lose their only
    non-tax classification, and nothing on screen says so. Emptying it first
    is one action away (assign them elsewhere), and then this is safe.
    """
    gid = str(p.get("group_id", "")).strip()
    with transaction(root, slug, "group.delete") as tx:
        groups = rows_of(root, slug, "groups.tsv")
        row = next((r for r in groups if r["group_id"] == gid), None)
        if row is None:
            raise DataError(f"növ tapılmadı: {gid}")
        assets = rows_of(root, slug, "assets.tsv")
        used = [r for r in assets if r.get("group_id") == gid]
        if used:
            raise DataError(
                f"«{row['name']}» növündə {len(used)} ƏV var — əvvəlcə onları "
                f"başqa növə keçirin və ya növü boşaldın"
            )
        tx.log("", "group", row["name"], "silindi")
        save_rows(root, slug, "groups.tsv",
                  [r for r in groups if r["group_id"] != gid])
    return gid


def assign_group(root: Path, slug: str, p: dict) -> str:
    """Put a batch of cards into a group (or take them out of one).

    A list rather than one card at a time for the reason §5.3-bis gives for
    set_writeoff: every write backs the folder up and recomputes every open
    year (§8.1), so forty separate calls would mean forty backups for one act
    of sorting. An empty `group_id` clears the field.

    A closed year is NOT a barrier here, unlike cost or date: the group
    reaches no figure, so putting a 2024 asset into «Serverlər» cannot change
    a filed return. Closing seals the return, not the card (§6.2).
    """
    ids = p.get("asset_ids") or ([p["asset_id"]] if p.get("asset_id") else [])
    gid = str(p.get("group_id", "")).strip()
    if not ids:
        raise DataError("ƏV seçilməyib")
    with transaction(root, slug, "group.assign") as tx:
        groups = rows_of(root, slug, "groups.tsv")
        if gid and not any(r["group_id"] == gid for r in groups):
            raise DataError(f"növ tapılmadı: {gid}")
        name = next((r["name"] for r in groups if r["group_id"] == gid), "")
        assets = rows_of(root, slug, "assets.tsv")
        by_id = {r["asset_id"]: r for r in assets}
        touched = 0
        for aid in ids:
            row = by_id.get(str(aid))
            if row is None:
                raise DataError(f"ƏV tapılmadı: {aid}")
            if row.get("group_id", "") == gid:
                continue
            # One line per card even though the act was one, same as a batch
            # purchase: grouping is for the person, not a licence to record
            # less of what happened (§5.3-bis).
            tx.log(row["asset_id"], "group_id", row.get("group_id", ""), gid)
            row["group_id"] = gid
            touched += 1
        save_rows(root, slug, "assets.tsv", assets)
    return f"{touched} ƏV → {name or '— növsüz —'}"

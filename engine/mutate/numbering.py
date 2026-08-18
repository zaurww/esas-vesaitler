"""Inventory numbers, internal ids and folder names.

`asset_id` is the immutable key; `inv_no` is the human one, editable and
reused after a disposal, which is why it is not the key (§4). A batch of N
identical assets gets a series computed from the first number rather than N
separate "what is next" questions -- asking again would drift onto whichever
prefix dominates the category."""

from __future__ import annotations

import re

from typing import Any

from ..storage import DataError

INV_PATTERN = re.compile(r"^(.*?)(\d+)$")


def suggest_inv_no(rows: list[dict[str, str]], category: str) -> str:
    """Propose the next inventory number, following whatever the client
    already uses rather than imposing a scheme.

    Numbering conventions differ per office and often arrive from 1C, so the
    prevailing prefix and zero-padding of that category are copied and the
    counter is stepped. Only when a category has none does it fall back to
    <CATEGORY>-0001. The suggestion is always editable -- it is a convenience,
    not a rule.
    """
    used = {r.get("inv_no", "").strip() for r in rows if r.get("inv_no", "").strip()}
    prefixes: dict[tuple[str, int], int] = {}
    for r in rows:
        if r.get("category") != category:
            continue
        m = INV_PATTERN.match(r.get("inv_no", "").strip())
        if m:
            key = (m.group(1), len(m.group(2)))
            prefixes[key] = max(prefixes.get(key, 0), int(m.group(2)))

    if prefixes:
        (prefix, width), top = max(prefixes.items(), key=lambda kv: (kv[1], kv[0][1]))
    else:
        prefix, width, top = f"{category.upper()}-", 4, 0

    n = top + 1
    while f"{prefix}{n:0{width}d}" in used:
        n += 1
    return f"{prefix}{n:0{width}d}"


def inv_series(rows: list[dict[str, str]], first: str, count: int) -> list[str]:
    """`count` inventory numbers, stepping the counter of `first`.

    Derived once from the starting number rather than by asking
    suggest_inv_no() again for every card. That function follows the prefix
    already prevailing in the category, so the moment a batch introduces a new
    one, the second call would jump back to whichever prefix holds the higher
    counter -- an MA-0008 landing in the middle of XOL-0001…XOL-0240.

    A starting number with no digits to step ("XOL") gets a counter appended;
    otherwise the numbers would collide and inv_no has to stay unique (§4).
    """
    used = {r.get("inv_no", "").strip() for r in rows if r.get("inv_no", "").strip()}
    m = INV_PATTERN.match(first)
    if m:
        prefix, width, n = m.group(1), len(m.group(2)), int(m.group(2))
    else:
        prefix, width, n = f"{first}-", 4, 1
    out: list[str] = []
    for _ in range(count):
        while f"{prefix}{n:0{width}d}" in used:
            n += 1
        number = f"{prefix}{n:0{width}d}"
        used.add(number)
        out.append(number)
        n += 1
    return out


ASSET_ID_FMT = "AV-{:03d}"


def next_asset_id(rows: list[dict[str, str]]) -> str:
    n = 0
    for r in rows:
        aid = r.get("asset_id", "")
        if aid.startswith("AV-") and aid[3:].isdigit():
            n = max(n, int(aid[3:]))
    return ASSET_ID_FMT.format(n + 1)


def asset_id_series(rows: list[dict[str, str]], count: int) -> list[str]:
    """`count` fresh ids in one pass.

    Asking for "the next id" once per card would rescan every row each time,
    turning a 240-card purchase into a quadratic walk for nothing.
    """
    start = int(next_asset_id(rows)[3:])
    return [ASSET_ID_FMT.format(start + i) for i in range(count)]


# A slipped digit turns 240 into 2400, and the guard is here rather than in the
# page because the page is not the only way in. Not a figure of the law, so it
# stays in code (§5.1-bis draws that line at what the tax code sets).
BATCH_MAX = 2000


def batch_count(value: Any) -> int:
    """How many identical cards this purchase creates.

    One card per physical object, always -- and not out of tidiness. The law
    tests per object: 240 refrigerators at 400 AZN each drop under the 114.8
    threshold one by one, while a single 96 000 AZN line never would, and a
    sale of three of them has to remove the residual of exactly those three
    (114.6). A quantity column would quietly cost the client the deduction.

    So the count belongs to the FORM, not to the data: it expands into rows
    here and is stored nowhere (§2 -- the fact is that 240 objects arrived).
    """
    raw = str(value or "").strip()
    if not raw:
        return 1
    if not raw.isdigit():
        raise DataError(f"Say tam ədəd olmalıdır, {raw!r} deyil")
    n = int(raw)
    if n < 1:
        raise DataError("Say ən azı 1 olmalıdır")
    if n > BATCH_MAX:
        raise DataError(
            f"Say {n} — səhv yazılış kimi görünür (maksimum {BATCH_MAX}). "
            f"Doğrudan bu qədərdirsə, alışı hissələrə bölün."
        )
    return n

SLUG_MAP = str.maketrans({
    # U+0307 first, and not for decoration: Python lowercases the Azerbaijani
    # «İ» to "i" PLUS a combining dot above, so every name containing one was
    # cut in half -- «Sınaq İdxal MMC» became `sinaq-i-dxal-mmc`, «İstehsal»
    # became `i-stehsal`. The letter is common enough that this was not rare.
    "̇": "",
    "ə": "e", "ç": "c", "ş": "s", "ğ": "g", "ı": "i", "ö": "o", "ü": "u",
    "Ə": "e", "Ç": "c", "Ş": "s", "Ğ": "g", "İ": "i", "Ö": "o", "Ü": "u",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "c", "ч": "c", "ш": "s", "щ": "s", "ы": "i", "э": "e",
    "ю": "u", "я": "a", "ъ": "", "ь": "",
})


def slugify(name: str) -> str:
    """Folder name from a company name. ASCII only: the folder is a path on
    someone else's Windows machine, and it is also the client's id in URLs."""
    s = str(name or "").strip().lower().translate(SLUG_MAP)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "musteri"


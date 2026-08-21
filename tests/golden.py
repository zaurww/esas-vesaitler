"""Freeze compute_year's full output for a real client, so a number nobody
thought to assert on is still caught when it drifts.

CLAUDE.md §5.6 asks for control examples before every release. Until this
existed, "control example" meant a handful of totals someone copied out by
hand into test_control_examples.py -- real regression protection, but only
for the figure a person remembered to write an assertion for. This freezes
EVERYTHING compute_year produces for the committed `demo-avto` client
(CLAUDE.md §3 -- committed on purpose) into tests/golden/<slug>.json, and
tests/test_golden.py diffs a fresh run against it.

Deliberately not `dataclasses.asdict(YearResult(...))` alone: about half of
what an accountant actually sees is a @property derived from stored fields
-- the declaration lines, a card's gross/accumulated columns (CardResult's
own docstring: "the tax pipeline only needs the residual, but the movement
statement... wants both halves") -- not a stored field itself, and asdict
only walks the latter. Both halves are captured here, so a regression in
either kind of number shows up the same way: a line in a diff.

`python ev.py golden` checks; `python ev.py golden --update` regenerates.
A genuine change (a law update, a bug fix) is expected to move this file --
that diff is exactly what belongs in the release notes for it (CLAUDE.md
§7's "версия, привязанная к цифрам").
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from engine.calc import CardResult, CategoryResult, YearResult, compute_year
from engine.storage import load_client

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
DEMO_SLUG = "demo-avto"


def _encode(obj):
    """Decimal -> its exact decimal text, date -> ISO, recurse through
    dict/list. Exact text rather than a rounded format: some rates are
    fractions with no two-decimal form (a straight-line term of 3 years is
    1/3, CLAUDE.md §5.3's "показывается срок... норма при этом показывается
    как 1/5") and a lossy format would make the snapshot disagree with
    itself on reload for no reason connected to the engine at all.
    """
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v) for v in obj]
    return obj


def _card_raw(c: CardResult) -> dict:
    d = dataclasses.asdict(c)
    # @property columns asdict cannot see (CardResult has no field for them):
    # the movement statement's gross/accumulated pairs (CLAUDE.md §11.3 --
    # real output on the "Kartlar" sheet and the card drawer), not just the
    # tax pipeline's residual.
    d.update(
        gross_start=c.gross_start, gross_in=c.gross_in, gross_out=c.gross_out,
        gross_end=c.gross_end, accumulated_start=c.accumulated_start,
        accumulated_out=c.accumulated_out, accumulated_end=c.accumulated_end,
    )
    return d


def _category_raw(cat: CategoryResult) -> dict:
    d = dataclasses.asdict(cat)
    d["cards"] = [_card_raw(c) for c in cat.cards]   # augmented, not asdict's bare version
    return d


def year_snapshot(r: YearResult) -> dict:
    """Every figure produced for one year, as a JSON-able dict.

    Client identity (name, VÖEN, slug, status) is left out on purpose --
    those are input echoes, not something the engine calculated, and
    including them would make every snapshot diff read as noise around the
    one line that actually moved. engine_version/format_version are left out
    for the same reason from the other direction: those change on every
    release regardless of whether a single number did, and the whole point
    is that `golden --update` should have nothing to show when a release
    changed no figures.
    """
    raw = {
        "totals": r.totals,
        "monthly": r.monthly,
        "disposal_gain": r.disposal_gain,
        "disposal_loss": r.disposal_loss,
        "warnings": r.warnings,
        "open_questions": r.open_questions,
        "carried_from_prev": r.carried_from_prev,
        "categories": [_category_raw(c) for c in r.categories],
        "declaration": [dataclasses.asdict(ln) for ln in r.declaration],
        "declaration_deducted": r.declaration_deducted,
        "declaration_income": r.declaration_income,
        "declaration_net": r.declaration_net,
    }
    return _encode(raw)


def client_snapshot(root: Path, slug: str) -> dict:
    """{year: year_snapshot(...)} for every year the client has a status row.

    Not web.app.available_years(): that extends to the current calendar
    year on purpose (CLAUDE.md §6.1, so a client can always be walked
    forward), which would make this set grow every New Year's Day for a
    reason that has nothing to do with the engine. A golden fixture needs a
    set of years that only changes when somebody deliberately changes it.
    """
    data = load_client(root, slug)
    years = sorted({s.year for s in data.statuses})
    return {str(y): year_snapshot(compute_year(data, y)) for y in years}


def golden_path(slug: str) -> Path:
    return GOLDEN_DIR / f"{slug}.json"


def read_golden(slug: str) -> dict | None:
    path = golden_path(slug)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_golden(root: Path, slug: str) -> Path:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = golden_path(slug)
    path.write_text(
        json.dumps(client_snapshot(root, slug), ensure_ascii=False, indent=2,
                   sort_keys=False) + "\n",
        encoding="utf-8")
    return path

#!/usr/bin/env python3
"""Əsas Vəsaitlər — CLI entry point.

    python ev.py                          start the local UI (default)
    python ev.py calc <client> <year>     print the year report to the console
    python ev.py export <client> <year>   write an .xlsx next to the client folder
    python ev.py close <client> <year>    close the year -> opening balances for year+1
    python ev.py verify <client>          recompute closed years, diff against stored
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.calc import MONTHS_AZ, CalcError, compute_year, money  # noqa: E402
from engine.excel import build_workbook  # noqa: E402
from engine.rates import ENGINE_VERSION  # noqa: E402
from engine.storage import (  # noqa: E402
    OPENING_HEADER, DataError, append_tsv, list_clients, load_client, read_tsv,
)


def cmd_calc(slug: str, year: int) -> None:
    r = compute_year(load_client(ROOT, slug), year)
    w = 15
    print(f"\n  {r.client_name} · VÖEN {r.voen} · {r.year}"
          f"{'  [İL BAĞLIDIR]' if r.is_closed else ''}")
    print(f"  {r.status_name} · engine {r.engine_version} · format v{r.format_version}\n")
    for cat in r.categories:
        ri = cat.rate
        print(f"  {cat.name_az}  —  {ri.statutory_max:.0%} × {ri.coefficient} "
              f"= {ri.ceiling:.0%} hədd, tətbiq {ri.applied:.0%}"
              f"{'  (fərdi dərəcələr var)' if cat.mixed_rates else
                 '  (həddən aşağı)' if ri.below_ceiling else ''}")
        print(f"    {'İnv.№':<10}{'Adı':<26}{'Qalıq(əvv)':>{w}}{'Daxil':>{w}}"
              f"{'Xaric':>{w}}{'Amort.':>{w}}{'Silinmə':>{w}}{'Qalıq(son)':>{w}}")
        for c in cat.cards:
            flag = "⚠" if c.threshold_hit else (" →" if c.disposal_type else "  ")
            print(f"  {flag}{c.inv_no:<10}{c.name[:25]:<26}"
                  f"{c.opening:>{w},.2f}{c.acquisition:>{w},.2f}{c.disposed:>{w},.2f}"
                  f"{c.depreciation:>{w},.2f}{c.writeoff:>{w},.2f}{c.closing:>{w},.2f}")
        print(f"    {'':<36}{cat.opening:>{w},.2f}{cat.acquisition:>{w},.2f}"
              f"{cat.disposed:>{w},.2f}{cat.depreciation:>{w},.2f}"
              f"{cat.writeoff:>{w},.2f}{cat.closing:>{w},.2f}\n")
    t = r.totals
    print(f"    {'C Ə M İ':<36}{t['opening']:>{w},.2f}{t['acquisition']:>{w},.2f}"
          f"{t['disposed']:>{w},.2f}{t['depreciation']:>{w},.2f}"
          f"{t['writeoff']:>{w},.2f}{t['closing']:>{w},.2f}")
    # The point of the whole run. Everything above is how these were arrived
    # at; the console used to stop before saying them, and the disposal
    # figures in particular appeared nowhere at all (§12.1).
    print("\n  BƏYANNAMƏYƏ GEDƏN MƏBLƏĞLƏR")
    for line in r.declaration:
        effect = "çıxılır" if line.effect == "deduction" else "gəlirə əlavə"
        print(f"    {line.article:<10}{line.label_az:<42}"
              f"{line.amount:>{w},.2f}  {effect}")
    print(f"    {'':<52}{'-' * w}")
    print(f"    {'Gəlirdən çıxılır':<52}{r.declaration_deducted:>{w},.2f}")
    print(f"    {'Gəlirə əlavə edilir':<52}{r.declaration_income:>{w},.2f}")
    print(f"    {'Vergi tutulan gəlirə təsir':<52}{r.declaration_net:>{w},.2f}")
    if r.disposed_cards:
        print("\n    Xaricetmə (m.114.6 — qalıq onsuz da bazadan çıxılıb):")
        for c in r.disposed_cards:
            when = c.disposal_date.isoformat() if c.disposal_date else "—"
            print(f"      {c.inv_no or c.name[:10]:<10}{c.name[:22]:<23}"
                  f"{c.disposal_type:<13}{when:<12}"
                  f"satış {c.proceeds:>11,.2f}  qalıq {c.disposed:>11,.2f}"
                  f"  fərq {c.gain_loss:>11,.2f}")

    print("\n  Aylıq amortizasiya (illik / 12):")
    for i, mm in enumerate(r.monthly):
        print(f"    {MONTHS_AZ[i]:<10}{mm:>12,.2f}", end="\n" if (i + 1) % 3 == 0 else "")
    for wmsg in r.warnings:
        print(f"  ⚠  {wmsg}")
    for q in r.open_questions:
        print(f"  ?  {q}")
    print()


def cmd_export(slug: str, year: int) -> None:
    data = load_client(ROOT, slug)
    r = compute_year(data, year)
    cp = {a.asset_id: a.counterparty for a in data.assets}
    out = ROOT / "clients" / slug / f"{slug}-{year}-amortizasiya.xlsx"
    out.write_bytes(build_workbook(r, cp))
    print(f"yazıldı: {out}")


def cmd_close(slug: str, year: int) -> None:
    """Write closing balances as next year's opening balances (CLAUDE.md §6)."""
    from engine.mutate import close_year
    print(close_year(ROOT, slug, {"year": year}))


def cmd_verify(slug: str) -> None:
    """Recompute every closed year and diff against the stored balances.

    Falls straight out of the event-sourced design (§2): a cheap regression
    detector across engine versions.
    """
    data = load_client(ROOT, slug)
    stored: dict[tuple[int, str], str] = {}
    for row in read_tsv(ROOT / "clients" / slug / "opening_balances.tsv"):
        if row.get("source") == "year_close":
            stored[(int(row["year"]), row["asset_id"])] = row["residual"].strip()
    bad = 0
    for year in sorted(data.closed_years()):
        r = compute_year(data, year)
        for c in r.cards:
            key = (year + 1, c.asset_id)
            if key not in stored:
                continue
            if f"{money(c.closing):.2f}" != f"{float(stored[key]):.2f}":
                bad += 1
                print(f"  ✗ {year}→{year+1} {c.asset_id}: "
                      f"saxlanmış {stored[key]} ≠ yenidən hesablanmış {money(c.closing):.2f}")
    print("  ✓ bütün bağlı illər uyğundur" if not bad else f"  {bad} uyğunsuzluq")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("serve", "ui"):
        from web.app import serve
        serve()
        return 0
    cmd = argv[0]
    try:
        if cmd == "clients":
            for s in list_clients(ROOT):
                print(" ", s)
        elif cmd == "calc":
            cmd_calc(argv[1], int(argv[2]))
        elif cmd == "export":
            cmd_export(argv[1], int(argv[2]))
        elif cmd == "close":
            cmd_close(argv[1], int(argv[2]))
        elif cmd == "verify":
            cmd_verify(argv[1])
        else:
            print(__doc__)
            return 2
    except (DataError, CalcError) as e:
        # §2.1 — report the failure, never substitute a plausible number.
        print(f"\n  XƏTA: {e}\n", file=sys.stderr)
        return 1
    except IndexError:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Local web UI on localhost. Stdlib http.server only, no framework.

The server holds no state: every request reloads the client folder and
recomputes from events (CLAUDE.md §2, §3).
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.calc import MONTHS_AZ, CalcError, compute_year  # noqa: E402
from engine.excel import build_workbook  # noqa: E402
from engine.rates import CATEGORIES, ENGINE_VERSION  # noqa: E402
from engine.storage import DataError, list_clients, load_client  # noqa: E402

INDEX = Path(__file__).resolve().parent / "index.html"


def m(x: Decimal) -> str:
    """Money as a plain string; the UI formats for display."""
    return f"{x:.2f}"


def available_years(data) -> list[int]:
    years = {ob.year for ob in data.opening_balances}
    years |= {s.year for s in data.statuses}
    years |= {a.in_date.year for a in data.assets if a.in_date}
    years = {y for y in years if y >= data.start_year}
    return sorted(years) or [data.start_year]


def serialize(r) -> dict:
    return {
        "client_name": r.client_name,
        "voen": r.voen,
        "slug": r.slug,
        "year": r.year,
        "is_closed": r.is_closed,
        "status": r.status,
        "status_name": r.status_name,
        "engine_version": r.engine_version,
        "format_version": r.format_version,
        "months": MONTHS_AZ,
        "totals": {k: m(v) for k, v in r.totals.items()},
        "monthly": [m(v) for v in r.monthly],
        "warnings": r.warnings,
        "open_questions": r.open_questions,
        "categories": [
            {
                "code": c.code,
                "name_az": c.name_az,
                "name_ru": c.name_ru,
                "mixed_rates": c.mixed_rates,
                "rate": {
                    "statutory_max": m(c.rate.statutory_max),
                    "statutory_year": c.rate.statutory_year,
                    "coefficient": str(c.rate.coefficient),
                    "ceiling": m(c.rate.ceiling),
                    "applied": m(c.rate.applied),
                    "elected": c.rate.elected,
                    "below_ceiling": c.rate.below_ceiling,
                    "below_statutory": c.rate.below_statutory,
                    "coefficient_used": c.rate.coefficient_used,
                    "source": c.rate.source,
                },
                "opening": m(c.opening),
                "acquisition": m(c.acquisition),
                "disposed": m(c.disposed),
                "depreciation": m(c.depreciation),
                "writeoff": m(c.writeoff),
                "closing": m(c.closing),
                "repair_limit": m(c.repair_limit),
                "repair_actual": m(c.repair_actual),
                "repair_deductible": m(c.repair_deductible),
                "repair_capitalized": m(c.repair_capitalized),
                "monthly": [m(v) for v in c.monthly],
                "cards": [
                    {
                        "asset_id": k.asset_id,
                        "inv_no": k.inv_no,
                        "name": k.name,
                        "category": k.category,
                        "in_date": k.in_date.isoformat() if k.in_date else "",
                        "cost": m(k.cost),
                        "is_legacy_pool": k.is_legacy_pool,
                        "opening": m(k.opening),
                        "acquisition": m(k.acquisition),
                        "repair_actual": m(k.repair_actual),
                        "repair_deductible": m(k.repair_deductible),
                        "repair_capitalized": m(k.repair_capitalized),
                        "disposed": m(k.disposed),
                        "base": m(k.base),
                        "rate": m(k.rate),
                        "depreciation": m(k.depreciation),
                        "writeoff": m(k.writeoff),
                        "closing": m(k.closing),
                        "rate_info": {
                            "statutory_max": m(k.rate_info.statutory_max),
                            "statutory_year": k.rate_info.statutory_year,
                            "coefficient": str(k.rate_info.coefficient),
                            "ceiling": m(k.rate_info.ceiling),
                            "applied": m(k.rate_info.applied),
                            "source": k.rate_info.source,
                            "below_ceiling": k.rate_info.below_ceiling,
                            "below_statutory": k.rate_info.below_statutory,
                            "coefficient_used": k.rate_info.coefficient_used,
                        } if k.rate_info else None,
                        "threshold_hit": k.threshold_hit,
                        "threshold_reason": k.threshold_reason,
                        "written_off": k.written_off,
                        "disposal_type": k.disposal_type,
                        "disposal_date": k.disposal_date.isoformat() if k.disposal_date else "",
                        "proceeds": m(k.proceeds),
                        "gain_loss": m(k.gain_loss),
                        "monthly": [m(v) for v in k.monthly],
                    }
                    for k in c.cards
                ],
            }
            for c in r.categories
        ],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "EsasVesaitler/" + ENGINE_VERSION

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
                return

            if url.path == "/api/context":
                slugs = list_clients(ROOT)
                out = []
                for s in slugs:
                    d = load_client(ROOT, s)
                    out.append({
                        "slug": s, "name": d.client_name, "voen": d.voen,
                        "years": available_years(d),
                        "closed_years": sorted(d.closed_years()),
                    })
                self._json({
                    "clients": out,
                    "engine_version": ENGINE_VERSION,
                    "categories": [
                        {"code": c.code, "name_az": c.name_az, "name_ru": c.name_ru}
                        for c in CATEGORIES
                    ],
                })
                return

            if url.path == "/api/report":
                slug = q.get("client", [""])[0]
                year = int(q.get("year", ["0"])[0])
                data = load_client(ROOT, slug)
                self._json(serialize(compute_year(data, year)))
                return

            if url.path == "/api/export":
                slug = q.get("client", [""])[0]
                year = int(q.get("year", ["0"])[0])
                data = load_client(ROOT, slug)
                blob = build_workbook(compute_year(data, year))
                fname = f"{slug}-{year}-amortizasiya.xlsx"
                self._send(
                    200, blob,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    {"Content-Disposition": f'attachment; filename="{fname}"'},
                )
                return

            self._json({"error": "not found"}, 404)

        except (DataError, CalcError) as e:
            # §2.1: a failed calculation is reported, never silently zeroed.
            self._json({"error": str(e), "kind": type(e).__name__}, 400)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}", "kind": "internal"}, 500)


def serve(port: int = 8777, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Əsas Vəsaitlər · engine {ENGINE_VERSION}")
    print(f"  {url}   (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    serve()

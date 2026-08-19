"""Creating a client folder and editing the firm's own details.

The folder is created complete, with every file the engine expects and headers
in place, so the store is valid from the first second rather than
materialising as features get used (§4)."""

from __future__ import annotations

import getpass
import os
import shutil
import tempfile
import tomllib
import uuid

from datetime import datetime, timezone
from pathlib import Path

from ..rates import FORMAT_VERSION
from ..storage import DataError, load_client, write_tsv

from .core import HEADERS, mutate_folder, save_rows, transaction
from .numbering import slugify
from .parse import _toml_str


def _write_config(folder: Path, *, client_name: str, voen: str, start_year: int,
                  format_version: int, client_id: str) -> None:
    """Atomic write for config.toml (§8), shared by create and update so the
    two paths cannot drift on the fields they write -- the way rates.tsv and
    the archive once did before NORM_FILES (§5.1)."""
    text = (
        f"client_name = {_toml_str(client_name)}\n"
        f"voen = {_toml_str(voen)}\n"
        f"start_year = {start_year}\n"
        f"format_version = {format_version}\n"
        f"client_id = {_toml_str(client_id)}\n"
    )
    path = folder / "config.toml"
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="\n", delete=False, dir=str(folder))
    try:
        tmp.write(text)
        tmp.close()
        os.replace(tmp.name, path)
    except BaseException:
        os.unlink(tmp.name)
        raise


def update_client(root: Path, slug: str, p: dict) -> str:
    """Edit the client's own details: name, VÖEN, first year.

    There was no way to do this at all -- the creation form asked once and
    that was final, so a typo in the name or the wrong VÖEN was permanent.

    The folder name is NOT among them. It is the client's identity: every
    backup, archive and URL carries it, and renaming it here would leave
    those pointing at nothing. Moving to a different name is export/import.
    """
    folder = mutate_folder(root, slug)
    cfg = tomllib.loads((folder / "config.toml").read_text(encoding="utf-8-sig"))
    name = str(p.get("client_name", cfg.get("client_name", ""))).strip()
    if not name:
        raise DataError("Müştərinin adı boş ola bilməz")
    voen = str(p.get("voen", cfg.get("voen", ""))).strip()
    try:
        year = int(p.get("start_year") or cfg.get("start_year"))
    except (TypeError, ValueError):
        raise DataError("İl düzgün deyil") from None
    if not (1990 < year < 2100):
        raise DataError(f"Başlanğıc il düzgün deyil: {year}")

    with transaction(root, slug, "client.update") as tx:
        for field, old, new in (("client_name", cfg.get("client_name", ""), name),
                                ("voen", cfg.get("voen", ""), voen),
                                ("start_year", str(cfg.get("start_year", "")), str(year))):
            if str(old) != str(new):
                tx.log("", field, str(old), str(new))
        # Re-read rather than reuse the `cfg` captured above: entering the
        # transaction may have just backfilled `client_id` (§8.3,
        # `_backup_key`), and writing the pre-transaction snapshot back out
        # would silently drop it again.
        fresh = tomllib.loads((folder / "config.toml").read_text(encoding="utf-8-sig"))
        _write_config(folder, client_name=name, voen=voen, start_year=year,
                      format_version=fresh.get("format_version", FORMAT_VERSION),
                      client_id=str(fresh.get("client_id", "")).strip()
                                or uuid.uuid4().hex)
    return slug

def create_client(root: Path, _slug: str, p: dict) -> str:
    """Create a client folder with every file the engine expects.

    A fresh install has no clients and no way to make one, which left the
    worker looking at an empty screen on day one. The files are created here,
    with headers only, so the store is valid from the first second rather
    than materialising piece by piece as features get used.
    """
    name = str(p.get("client_name", "")).strip()
    if not name:
        raise DataError("Müştərinin adı boş ola bilməz")
    voen = str(p.get("voen", "")).strip()
    try:
        year = int(p.get("start_year") or 0)
    except ValueError:
        raise DataError("İl düzgün deyil") from None
    if not (1990 < year < 2100):
        raise DataError(f"Başlanğıc il düzgün deyil: {p.get('start_year')!r}")
    status = str(p.get("status", "orta")).strip()
    if status not in ("mikro", "kicik", "orta", "iri"):
        raise DataError("Status: mikro | kicik | orta | iri")

    slug = slugify(p.get("slug") or name)
    folder = root / "clients" / slug
    if folder.exists():
        raise DataError(f"«{slug}» qovluğu artıq mövcuddur")
    folder.mkdir(parents=True)

    try:
        _write_config(folder, client_name=name, voen=voen, start_year=year,
                      format_version=FORMAT_VERSION, client_id=uuid.uuid4().hex)
        for fname, header in HEADERS.items():
            write_tsv(folder / fname, header, [])
        # A year with no taxpayer status cannot be computed, so seed the one
        # the client starts in -- otherwise the first screen is an error.
        save_rows(root, slug, "taxpayer_status.tsv",
                  [{"year": str(year), "status": status, "basis": "",
                    "use_coefficient": ""}])
        save_rows(root, slug, "changelog.tsv", [{
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "user": getpass.getuser(), "action": "client.create",
            "asset_id": "", "field": "client", "old_value": "",
            "new_value": f"{name} ({slug})",
        }])
        load_client(root, slug)          # must parse before we hand it back
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return slug



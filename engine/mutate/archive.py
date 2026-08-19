"""Moving a client between machines as one .zip (§8.2).

Copying the folder is not enough and both ways of getting it wrong are silent:
the norms live next to the engine, not in the client folder, and an older
engine on the target machine ignores files it does not know about. So the
archive carries the norms and a manifest, and the import compares before it
writes."""

from __future__ import annotations

import getpass
import hashlib
import io
import json
import shutil
import zipfile

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import rates
from ..calc import compute_year
from ..rates import ENGINE_VERSION, FORMAT_VERSION, version_tuple
from ..storage import DataError, load_client

from .core import mutate_folder, one_segment
from .numbering import slugify

# Copying the folder is not enough, and the ways it goes wrong are silent:
#
#   * the norms in rates.tsv / coefficients.tsv live NEXT TO THE ENGINE, not
#     in the client folder. A client carried alone lands on the target
#     machine's norms and quietly computes different numbers.
#   * an older engine on the target machine does not know files added later
#     (additions.tsv, and columns like use_coefficient). It does not fail --
#     it just does not read them, and the result is off with no error.
#
# So an archive carries the norms and records which engine wrote the data,
# and the import compares before it writes.

ARCHIVE_MANIFEST = "manifest.json"


def export_client(root: Path, slug: str) -> bytes:
    import hashlib
    import json
    import zipfile

    folder = mutate_folder(root, slug)
    data = load_client(root, slug)
    buf = io.BytesIO()
    files = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.suffix not in (".tsv", ".toml"):
                continue
            raw = f.read_bytes()
            files[f.name] = hashlib.sha256(raw).hexdigest()
            z.writestr(f"client/{f.name}", raw)
        for name in rates.NORM_FILES:
            p = root / name
            if p.exists():
                z.writestr(f"norms/{name}", p.read_bytes())
        z.writestr(ARCHIVE_MANIFEST, json.dumps({
            "slug": slug,
            "client_name": data.client_name,
            "voen": data.voen,
            "engine_version": ENGINE_VERSION,
            "format_version": data.format_version,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "exported_by": getpass.getuser(),
            "files": files,
        }, ensure_ascii=False, indent=2))
    return buf.getvalue()


def inspect_archive(root: Path, blob: bytes) -> dict:
    """Read the archive and say what importing it would mean, without writing."""
    import json
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(blob))
    try:
        man = json.loads(z.read(ARCHIVE_MANIFEST).decode("utf-8"))
    except KeyError:
        raise DataError("Bu arxiv proqram tərəfindən yaradılmayıb "
                        "(manifest.json yoxdur)") from None

    notes, blocking = [], []
    if version_tuple(man["engine_version"]) > version_tuple(ENGINE_VERSION):
        blocking.append(
            f"Arxiv daha yeni mühərriklə ({man['engine_version']}) yazılıb, "
            f"burada {ENGINE_VERSION} var. Əvvəlcə proqramı yeniləyin — köhnə "
            f"mühərrik yeni məlumatın bir hissəsini sadəcə oxumur və rəqəmlər "
            f"səhv çıxır."
        )
    if man["format_version"] != FORMAT_VERSION:
        notes.append(f"Format v{man['format_version']} → v{FORMAT_VERSION}.")

    for name in rates.NORM_FILES:
        try:
            theirs = z.read(f"norms/{name}")
        except KeyError:
            theirs = b""
        p = root / name
        ours = p.read_bytes() if p.exists() else b""
        if theirs.strip() != ours.strip():
            notes.append(
                f"«{name}» fərqlidir: normalar müştəri qovluğunda deyil, "
                f"proqramın yanında saxlanılır. Arxivdəki variantı tətbiq "
                f"etməsəniz, rəqəmlər bu maşında başqa cür çıxacaq."
            )

    # Not blocking: importing under a different name is a normal thing to do,
    # so the collision is reported and the caller picks a target.
    exists = (root / "clients" / man["slug"]).exists()
    if exists:
        notes.append(f"«{man['slug']}» qovluğu artıq mövcuddur — "
                     f"başqa ad seçin.")
    return {"manifest": man, "notes": notes, "blocking": blocking,
            "exists": exists, "suggested_slug": man["slug"]}


def import_client(root: Path, _slug: str, p: dict) -> Any:
    import base64
    import json
    import zipfile

    blob = base64.b64decode(p.get("b64", ""))
    info = inspect_archive(root, blob)
    if p.get("dry_run"):
        return info
    if info["blocking"]:
        raise DataError(" ".join(info["blocking"]))

    z = zipfile.ZipFile(io.BytesIO(blob))
    man = info["manifest"]
    # Through slugify, not raw: this is the one place a folder is CREATED from
    # a name the request supplies. Taking it verbatim both broke the ASCII rule
    # of §4 (a Cyrillic "е" produced a folder no URL could carry) and let the
    # path point outside clients/ entirely.
    slug = slugify(p.get("slug") or man["slug"])
    if not slug:
        raise DataError("Qovluq adı boşdur")
    folder = root / "clients" / one_segment(slug)
    if folder.exists():
        raise DataError(f"«{slug}» qovluğu artıq mövcuddur")
    folder.mkdir(parents=True)
    try:
        for entry in z.namelist():
            if entry.startswith("client/") and not entry.endswith("/"):
                (folder / Path(entry).name).write_bytes(z.read(entry))
        if p.get("apply_norms"):
            for name in rates.NORM_FILES:
                try:
                    (root / name).write_bytes(z.read(f"norms/{name}"))
                except KeyError:
                    pass
            rates.refresh(root)
        data = load_client(root, slug)
        closed = data.closed_years()
        for st in data.statuses:
            if st.year not in closed:
                compute_year(data, st.year)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {"slug": slug, "notes": info["notes"]}


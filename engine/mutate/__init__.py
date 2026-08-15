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

--------------------------------------------------------------------------

This was one 1 610-line module. It was split because it had stopped being one
thing: transactions, number parsing, inventory numbering, the actions
themselves, archives and the import wizard had nothing in common except living
in the same file. Nothing moved between behaviours -- the split is mechanical,
and the suite (§11.4) is what says so.

    core        backup / write / re-read / roll back, and the closed-year guard
    parse       what a person typed -> what the store holds, and back
    numbering   inv_no series, asset_id, slug
    assets      the card and everything that happens to one
    clients     creating a client, editing the firm's own details
    archive     moving a client between machines
    decisions   status, elected rate, write-off, closing a year
    norms       the owner's edits to the figures of the law
    imports     bulk import from someone else's workbook

The names below are re-exported so that callers -- `web/app.py`, `ev.py`, the
tests -- import from `engine.mutate` exactly as before. Where a caller wants
something narrower it can import the submodule directly; both work.
"""

from .core import (
    HEADERS, Tx, guard_open_year, mutate_folder, one_segment, rows_of,
    save_rows, transaction,
)
from .parse import category_of, dec, iso_date
from .numbering import (
    BATCH_MAX, asset_id_series, batch_count, inv_series, next_asset_id,
    slugify, suggest_inv_no,
)
from .assets import (
    MODES, add_addition, add_repair, create_asset, delete_asset,
    remove_addition, remove_repair, set_disposal, set_opening, update_asset,
)
from .clients import create_client, update_client
from .archive import export_client, import_client, inspect_archive
from .decisions import (
    close_year, reopen_year, set_election, set_status, set_writeoff,
)
from .norms import set_coefficient_row, set_parameter_row, set_rate_row
from .imports import IMPORT_ALIASES, IMPORT_FIELDS, guess_columns, import_assets

# What the UI is allowed to ask for. One name per action, so an unknown action
# is refused by lookup rather than by dispatching into something unintended.
ACTIONS = {
    "asset.import": import_assets,
    "rate.set": set_rate_row,
    "coefficient.set": set_coefficient_row,
    "parameter.set": set_parameter_row,
    "asset.create": create_asset,
    "asset.update": update_asset,
    "asset.delete": delete_asset,
    "opening.set": set_opening,
    "disposal.set": set_disposal,
    "repair.add": add_repair,
    "addition.add": add_addition,
    "addition.remove": remove_addition,
    "repair.remove": remove_repair,
    "writeoff.set": set_writeoff,
    "election.set": set_election,
    "status.set": set_status,
    "client.create": create_client,
    "client.update": update_client,
    "client.import": import_client,
    "year.close": close_year,
    "year.reopen": reopen_year,
}

__all__ = [
    "ACTIONS", "BATCH_MAX", "HEADERS", "IMPORT_ALIASES", "IMPORT_FIELDS",
    "MODES", "Tx", "add_addition", "add_repair", "asset_id_series",
    "batch_count", "category_of", "close_year", "create_asset",
    "create_client", "dec", "delete_asset", "export_client", "guard_open_year",
    "guess_columns", "import_assets", "import_client", "inspect_archive",
    "inv_series", "iso_date", "mutate_folder", "next_asset_id", "one_segment",
    "remove_addition", "remove_repair", "reopen_year", "rows_of", "save_rows",
    "set_coefficient_row", "set_disposal", "set_election", "set_opening",
    "set_parameter_row", "set_rate_row", "set_status", "set_writeoff",
    "slugify", "suggest_inv_no", "transaction", "update_asset",
    "update_client",
]

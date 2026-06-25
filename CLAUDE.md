# CLAUDE.md — project guide for MyDb

This file is read automatically by Claude Code at the start of a session. It
exists so a fresh Claude instance (e.g. on another machine) understands **what**
MyDb is and **why** it is built the way it is, and can keep working confidently.

## What this is

MyDb is a small **Windows desktop app** (Python 3 + Tkinter + SQLite) for a
Latvian user. It manages **products / positions** and assembles them into
**recipes** (a bill of materials of "nested codes"), then computes **nutritional
values per 100 g**. Units are Latvian: `gab.` (gabali / pieces) and `kg`.

Long-term goals the user has stated: full **recipe + nutrition-label output**,
**cost** tracking, and a **shared/cloud database** so multiple people can use it.

## Run & test

- Run the app (no console window): `pythonw app.py`
- Run with a console (to see errors while debugging): `python app.py`
- Tests (run from the project directory): `python -m unittest` — ~44 tests.
- `mydb.sqlite3` is created next to the code on first run. It is **local data and
  git-ignored**, so it does NOT travel with the repo (see "Data & deployment").

Environment: Windows, Python 3.13, Tcl/Tk 8.6.15. The shell is PowerShell.

## Files

- `app.py` — Tkinter GUI: the main window (product catalog + groups + search) and
  per-position "card" windows (details, description, nested codes, nutrition).
  **The GUI only ever talks to the data layer through functions in `db.py`.**
- `db.py` — SQLite data layer: schema, migrations, all read/write helpers, and the
  nutrition math. **All persistence logic lives here** — keep it that way so the
  storage can later be swapped (e.g. for a cloud DB) without touching the GUI.
- `test_db.py` — unittest tests for `db.py` (each test uses a fresh in-memory DB).
- `test_app.py` — tests for pure helpers in `app.py` that need no running GUI.

## Data model (tables, all defined in `db.py:init_db`)

- **products** (a "position"): `code` (UNIQUE), `name`, `quantity`, `unit`
  (`'gab.'` or `'kg'`), `description`, `weight_kg`, six per-100 g nutrition columns
  (`fat, saturated_fat, carbs, sugar, protein, salt`), `group_id` (nullable).
- **components** (a "nested code" — one ingredient line of a recipe):
  `parent_product_id` (FK → products, `ON DELETE CASCADE`), `child_code` (the
  *code* of another position), `quantity`. A component has **no unit or name of
  its own**; they are resolved live from the referenced position.
- **groups**: `id`, `name` (UNIQUE). A product optionally belongs to one group;
  deleting a group ungroups its products (`ON DELETE SET NULL`).

## Key design decisions (the "why")

- **A nested code references another position and stores only a quantity.** Its
  name *and unit* are looked up from the referenced position (`list_components`
  joins `products` on `code`). So a position's unit is set in ONE place and every
  nesting of it follows automatically. (Units used to be stored per-nesting; that
  was wrong and has been migrated away.)
- **Unit meaning / weight:** `kg` → the quantity is kilograms (1 unit = 1 kg).
  `gab.` → pieces, and each piece weighs `weight_kg`. So a component's mass is
  `quantity × child.weight_kg × 1000` grams for both units. `weight_kg` is forced
  to 1 for `kg` positions and is only shown/edited for `gab.` ones.
- **Quantity scaling:** changing a position's quantity scales all its nested codes
  by the same factor (`new / old`) — a nested quantity is the amount needed for the
  position's *current* quantity. Skipped when the old quantity is 0 (no ratio).
- **Nutrition is per 100 g.** The six macros are entered manually (the `uzturvielas`
  window) for raw ingredients. `kcal = fat×9 + carbs×4 + protein×4`;
  `kJ = kcal × 4.184`.
- **Computed nutrition roll-up** (`db.effective_nutrition`): a position WITH nested
  codes is a recipe; its per-100 g nutrition is computed by mass from its
  ingredients (each ingredient's per-100 g × its grams, summed, ÷ total grams ×
  100). It **recurses** into sub-recipes and is **cycle-safe** (a `_visiting` set).
  A raw position (no nested codes) just returns its stored values. The card shows
  this in a right-side panel when the checkbox right of `uzturvielas` is ticked.
- **Decimals:** values are stored to 5 decimals (`QUANTITY_DECIMALS`) and shown via
  `db.format_quantity()` — always ≥2 and ≤5 decimals, trailing zeros trimmed
  (`1` → `1.00`, `1.3` → `1.30`, `1.23456` → `1.23456`).
- **Latvian keyboard input fix** (`app.fix_baltic_char` / `enable_latvian_input`):
  Tk 8.6 on Windows mis-decodes AltGr Latvian letters through Latin-1 (cp1252)
  instead of Baltic (cp1257), so `ļ` arrives as `ï`. The fix re-encodes the
  character via cp1252 and decodes it via cp1257 to recover the intended letter.
  Applied to the Code/Name/Description fields, the search box, and the group-name
  prompt. **Do not remove this — it is why Latvian typing works in the app.**
- **The main window is a catalog, not a stock count** — it shows Code/Name/Unit,
  no quantity column. Quantity lives in the card (it drives recipe scaling).

## Conventions

- Keep ALL database logic in `db.py`; the GUI calls its functions only.
- Schema changes are **additive migrations** in `db.py:init_db` (`_migrate_*`
  helpers add columns / rebuild tables on existing databases, preserving data).
  **Back up `mydb.sqlite3` before testing a schema change** against real data.
- Every `db.py` behavior has a unittest. Run `python -m unittest` before committing.
- Git: feature branch → PR → merge into `main`. PowerShell mangles heredocs, so
  pass multi-line commit/PR text via a file (`git commit -F file`,
  `gh pr create --body-file`) or several `-m` flags.

## Data & deployment

- `mydb.sqlite3` is **local and git-ignored** — the repo carries code, not data.
  Moving to another machine: clone the repo (`gh repo clone Krabus92/MyDb`), but
  copy `mydb.sqlite3` separately if you want the existing data. (A built-in
  export/import/backup is a planned feature — see roadmap.)
- GitHub repo `Krabus92/MyDb`, default branch `main`, is the source of truth.

## Current state & next steps

**Done:** per-position cards, nested-code picker/edit, shared unit + migration,
quantity scaling, 5-decimal display, description, Latvian input fix, Ok/Cancel
with confirmations, weight, nutrition entry + per-100 g computed roll-up, groups
+ filtering, right-click menus, product search, and code-rename cascade.

**Known limitations / good next tasks:**
- References are by `code` string, not an id FK. Renames now cascade
  (`update_product`), but **deleting** an ingredient still orphans nested codes to
  `(unknown)`, and **indirect cycles** (A→B→A) are not rejected (only direct
  self-nesting is). A more robust fix is to reference children by `product_id`.
- No in-app **export / import / backup** (needed for multi-PC use).
- Decimal input only accepts `.` (Latvian users may type `,`).
- Planned features: printable **recipe + nutrition-label** output, **cost**
  tracking, **cloud/shared DB** for multiple users, standalone **.exe** packaging
  (see open PR #3, branch `feat/exe-packaging`).
- No CI yet — running `python -m unittest` in GitHub Actions on push would guard
  the test suite.

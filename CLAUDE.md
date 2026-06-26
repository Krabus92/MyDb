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
- Tests (run from the project directory): `python -m unittest` — ~47 tests.
- Build a standalone `.exe` (no Python needed to run it): `.\build_exe.ps1` →
  `dist\MyDb.exe`. The packaged app stores its database next to the `.exe`.
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
- `foodsource.py` — Open Food Facts lookup (search by name or barcode → per-100 g
  nutrition). The **only** module that uses the network: the GUI calls it, lets
  the user review, then saves through `db.py`. Stdlib `urllib` only (no new build
  dependency). `parse_off_product` is a pure, tested mapper.
- `test_db.py` — unittest tests for `db.py` (each test uses a fresh in-memory DB).
- `test_app.py` — tests for pure helpers in `app.py` that need no running GUI.
- `test_foodsource.py` — tests for the pure `parse_off_product` mapper (no network).
- `build_exe.ps1` / `requirements-dev.txt` — build a standalone Windows `.exe`
  with PyInstaller. Build output (`dist/`, `build/`, `*.spec`) is git-ignored.

## Data model (tables, all defined in `db.py:init_db`)

- **products** (a "position"): `code` (UNIQUE), `name`, `quantity`, `unit`
  (`'gab.'` or `'kg'`), `description`, `weight_kg`, six per-100 g nutrition columns
  (`fat, saturated_fat, carbs, sugar, protein, salt`), `group_id` (nullable), and
  `show_computed` (0/1 — whether the card reopens with the computed panel shown).
- **components** (a "nested code" — one ingredient line of a recipe):
  `parent_product_id` (FK → products, `ON DELETE CASCADE`), `child_product_id`
  (FK → products, `ON DELETE CASCADE` — the nested position), `quantity`. A
  component has **no unit or name of its own**; they are resolved live from the
  referenced position.
- **groups**: `id`, `name` (UNIQUE). A product optionally belongs to one group;
  deleting a group ungroups its products (`ON DELETE SET NULL`).

## Key design decisions (the "why")

- **A nested code references another position by id and stores only a quantity.**
  Its code, name *and unit* are looked up from the referenced position
  (`list_components` joins `products` on `id` via `child_product_id`). So a
  position's unit is set in ONE place and every nesting of it follows
  automatically, renaming a code is reflected with no cascade, and deleting a
  position removes the nested lines that used it (FK `ON DELETE CASCADE`).
  `add_component` rejects self-nesting and indirect cycles (A→B→A). (Earlier
  versions stored a per-nesting unit, and referenced the child by its code
  string; both were wrong and have been migrated away.)
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
  codes is a recipe; its per-100 g nutrition is the nutrients its ingredients
  contribute (each ingredient's per-100 g × its grams, summed — see
  `db.recipe_nutrient_grams`) **÷ the position's OWN declared mass** (
  `db.position_mass_grams` = `weight_kg × quantity × 1000` g; quantity 0 counts as
  one unit) × 100. So the position's *own weight* is the 100 g basis — a 1 kg
  position holding 2 kg of an ingredient is **twice as concentrated** as that
  ingredient (think cooking-down / reduction). It **recurses** into sub-recipes
  and is **cycle-safe** (a `_visiting` set); per-100 g is invariant to quantity
  (nested codes scale with it, so the basis scales too). A raw position (no nested
  codes) returns its stored values. The card shows this in a right-side panel when
  the checkbox right of `uzturvielas` is ticked, and it updates live as you edit
  weight/quantity; while it is shown the manual `uzturvielas` editor is **disabled**
  so manual values can't conflict with the computed ones. The checkbox state is
  saved per position (`show_computed`), so a card reopens as you left it, and the
  window auto-sizes (`geometry("")`) to fit the panel rather than clipping it.
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
+ filtering, right-click menus, product search, nested codes referenced by
`product_id` (delete-cascade, no orphans, indirect-cycle rejection), standalone
**.exe** packaging (`build_exe.ps1`), and **Open Food Facts** nutrition import
(search by name or barcode — fill an existing position's nutrition, or create a
new position pre-filled from the result).

**Known limitations / good next tasks:**
- No in-app **export / import / backup** (needed for multi-PC use).
- Decimal input only accepts `.` (Latvian users may type `,`).
- Planned features: printable **recipe + nutrition-label** output, **cost**
  tracking, and a **cloud/shared DB** for multiple users.
- No CI yet — running `python -m unittest` in GitHub Actions on push would guard
  the test suite.

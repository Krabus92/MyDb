"""SQLite data layer for MyDb.

Holds two tables:

* ``products``   — one row per position (code, name, quantity, unit)
* ``components`` — positions nested under another, each with its own quantity

A nested code references *another position* by its id (``child_product_id``).
Its code, name and unit are not copied into the components table; they are read
live by joining back to ``products`` (see :func:`list_components`), so a nested
code always reflects the current state of the position it points to — renaming
that position is automatic, and deleting it removes the nested lines that used
it (foreign key ``ON DELETE CASCADE``).

The GUI in :mod:`app` talks to the database only through the helpers here, so
the storage logic stays in one place and is easy to test.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def _base_dir() -> Path:
    """Folder the database should live in.

    When running as a PyInstaller one-file ``.exe``, ``__file__`` points inside
    a temporary extraction folder that is deleted on exit, so the database is
    stored next to the executable instead. Otherwise it sits next to this
    source file.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


#: Default location of the database file.
DB_PATH = _base_dir() / "mydb.sqlite3"

#: The only units a position or nested code may use.
VALID_UNITS = ("gab.", "kg")


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the tables if they do not already exist, and migrate old ones.

    A nested code has no unit of its own: its unit is that of the position it
    references (see :func:`list_components`), so a position's unit is set in one
    place and shared by every nesting of it.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS groups (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            code          TEXT NOT NULL UNIQUE,
            name          TEXT NOT NULL,
            quantity      REAL NOT NULL DEFAULT 0,
            unit          TEXT NOT NULL CHECK (unit IN ('gab.', 'kg')),
            description   TEXT NOT NULL DEFAULT '',
            -- Weight of one unit in kg. A 'kg' position weighs 1 kg per unit;
            -- a 'gab.' (piece) position carries the weight of one piece here.
            weight_kg     REAL NOT NULL DEFAULT 1,
            -- Nutrition per 100 g of product (grams). kcal/kJ are computed.
            fat           REAL NOT NULL DEFAULT 0,
            saturated_fat REAL NOT NULL DEFAULT 0,
            carbs         REAL NOT NULL DEFAULT 0,
            sugar         REAL NOT NULL DEFAULT 0,
            protein       REAL NOT NULL DEFAULT 0,
            salt          REAL NOT NULL DEFAULT 0,
            -- Optional group; NULL means ungrouped (shown only under "All").
            group_id      INTEGER REFERENCES groups (id) ON DELETE SET NULL,
            -- Whether the card opens with the computed-nutrition panel shown.
            show_computed INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS components (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_product_id INTEGER NOT NULL,
            child_product_id  INTEGER NOT NULL,
            quantity          REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (parent_product_id)
                REFERENCES products (id) ON DELETE CASCADE,
            FOREIGN KEY (child_product_id)
                REFERENCES products (id) ON DELETE CASCADE
        );
        """
    )
    _migrate_drop_component_unit(conn)
    _migrate_add_product_columns(conn)
    _migrate_components_to_product_id(conn)
    conn.commit()


def _migrate_add_product_columns(conn: sqlite3.Connection) -> None:
    """Add product columns introduced after the original schema, if missing."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
    additions = [
        ("description", "TEXT NOT NULL DEFAULT ''"),
        ("weight_kg", "REAL NOT NULL DEFAULT 1"),
        ("fat", "REAL NOT NULL DEFAULT 0"),
        ("saturated_fat", "REAL NOT NULL DEFAULT 0"),
        ("carbs", "REAL NOT NULL DEFAULT 0"),
        ("sugar", "REAL NOT NULL DEFAULT 0"),
        ("protein", "REAL NOT NULL DEFAULT 0"),
        ("salt", "REAL NOT NULL DEFAULT 0"),
        ("group_id", "INTEGER REFERENCES groups (id) ON DELETE SET NULL"),
        ("show_computed", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for name, decl in additions:
        if name not in existing:
            conn.execute(f"ALTER TABLE products ADD COLUMN {name} {decl}")


def _migrate_drop_component_unit(conn: sqlite3.Connection) -> None:
    """Drop the legacy ``components.unit`` column if an old database still has it.

    Older versions stored a unit per nested code. The unit now lives only on the
    referenced position, so rebuild ``components`` without that column, keeping
    every existing nested code's quantity and reference intact.
    """
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(components)")]
    if "unit" not in columns:
        return
    conn.executescript(
        """
        CREATE TABLE components_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_product_id INTEGER NOT NULL,
            child_code        TEXT NOT NULL,
            quantity          REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (parent_product_id)
                REFERENCES products (id) ON DELETE CASCADE
        );

        INSERT INTO components_new (id, parent_product_id, child_code, quantity)
            SELECT id, parent_product_id, child_code, quantity FROM components;

        DROP TABLE components;
        ALTER TABLE components_new RENAME TO components;
        """
    )


def _migrate_components_to_product_id(conn: sqlite3.Connection) -> None:
    """Replace the legacy ``components.child_code`` text with a ``child_product_id``.

    Older versions referenced a nested position by its *code* string. Referencing
    it by id instead means: renames need no cascade (the join is by id), deleting
    an ingredient cleanly removes the nested lines that used it (FK ``ON DELETE
    CASCADE``) instead of orphaning them to ``(unknown)``, and cycles can be
    detected reliably. Nested rows whose old ``child_code`` matched no position
    (references that were already orphaned) are dropped, since an id reference
    must point at a real position.
    """
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(components)")]
    if "child_code" not in columns:
        return
    conn.executescript(
        """
        CREATE TABLE components_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_product_id INTEGER NOT NULL,
            child_product_id  INTEGER NOT NULL,
            quantity          REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (parent_product_id)
                REFERENCES products (id) ON DELETE CASCADE,
            FOREIGN KEY (child_product_id)
                REFERENCES products (id) ON DELETE CASCADE
        );

        INSERT INTO components_new
                (id, parent_product_id, child_product_id, quantity)
            SELECT c.id, c.parent_product_id, p.id, c.quantity
            FROM components c
            JOIN products p ON p.code = c.child_code;

        DROP TABLE components;
        ALTER TABLE components_new RENAME TO components;
        """
    )


#: Quantities are stored with at most this many digits after the decimal point.
QUANTITY_DECIMALS = 5

#: Quantities are always shown with at least this many decimals (e.g. "1.00").
QUANTITY_MIN_DECIMALS = 2


def _check_unit(unit: str) -> None:
    if unit not in VALID_UNITS:
        raise ValueError(f"unit must be one of {VALID_UNITS}, got {unit!r}")


def _round_qty(quantity: float) -> float:
    """Clamp a quantity to :data:`QUANTITY_DECIMALS` digits after the decimal."""
    return round(float(quantity), QUANTITY_DECIMALS)


def format_quantity(quantity: float) -> str:
    """Format a quantity for display.

    Always shows at least :data:`QUANTITY_MIN_DECIMALS` decimals and at most
    :data:`QUANTITY_DECIMALS`, dropping any trailing zeros in between. So
    ``1`` -> ``"1.00"``, ``1.3`` -> ``"1.30"``, ``1.30000`` -> ``"1.30"`` and
    ``1.23456`` -> ``"1.23456"``.
    """
    text = f"{_round_qty(quantity):.{QUANTITY_DECIMALS}f}".rstrip("0")
    integer, _, frac = text.partition(".")
    return f"{integer}.{frac.ljust(QUANTITY_MIN_DECIMALS, '0')}"


# ----- nutrition energy ------------------------------------------------

#: The six per-100 g nutrition values stored on every position.
NUTRIENTS = ("fat", "saturated_fat", "carbs", "sugar", "protein", "salt")

#: Energy per gram of macronutrient, in kcal.
KCAL_PER_GRAM_FAT = 9.0
KCAL_PER_GRAM_CARBS = 4.0
KCAL_PER_GRAM_PROTEIN = 4.0

#: 1 kcal in kilojoules.
KJ_PER_KCAL = 4.184


def energy_kcal(fat: float, carbs: float, protein: float) -> float:
    """Energy in kcal from macros (per whatever basis the macros are given)."""
    return (
        fat * KCAL_PER_GRAM_FAT
        + carbs * KCAL_PER_GRAM_CARBS
        + protein * KCAL_PER_GRAM_PROTEIN
    )


def energy_kj(fat: float, carbs: float, protein: float) -> float:
    """Energy in kilojoules from macros."""
    return energy_kcal(fat, carbs, protein) * KJ_PER_KCAL


# ----- positions (products) --------------------------------------------


#: Every column read back for a position, in a single place.
_PRODUCT_FIELDS = (
    "id, code, name, quantity, unit, description, weight_kg, "
    "fat, saturated_fat, carbs, sugar, protein, salt, group_id, show_computed"
)


def add_product(
    conn: sqlite3.Connection,
    code: str,
    name: str,
    quantity: float,
    unit: str,
    description: str = "",
    weight_kg: float = 1.0,
    group_id: int | None = None,
) -> int:
    """Insert a position and return its new row id.

    ``weight_kg`` is the weight of one unit: a ``kg`` position is 1 kg per unit,
    a ``gab.`` (piece) position carries the weight of one piece. Nutrition starts
    at zero and is set later via :func:`update_nutrition`. ``group_id`` is the
    group the position belongs to, or ``None`` for ungrouped.
    """
    _check_unit(unit)
    cur = conn.execute(
        """
        INSERT INTO products
            (code, name, quantity, unit, description, weight_kg, group_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code, name, _round_qty(quantity), unit, description,
            _round_qty(weight_kg), group_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_products(
    conn: sqlite3.Connection, group_id: int | None = None
) -> list[sqlite3.Row]:
    """Return positions ordered by code; all of them, or only one group's.

    ``group_id`` of ``None`` (the default) returns every position; a group id
    returns only the positions in that group.
    """
    if group_id is None:
        return conn.execute(
            f"SELECT {_PRODUCT_FIELDS} FROM products ORDER BY code"
        ).fetchall()
    return conn.execute(
        f"SELECT {_PRODUCT_FIELDS} FROM products WHERE group_id = ? ORDER BY code",
        (group_id,),
    ).fetchall()


def get_product(conn: sqlite3.Connection, product_id: int) -> sqlite3.Row | None:
    """Return one position by id, or ``None`` if it does not exist."""
    return conn.execute(
        f"SELECT {_PRODUCT_FIELDS} FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()


def find_product_by_code(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    """Return one position by its code, or ``None`` if no position uses it."""
    return conn.execute(
        f"SELECT {_PRODUCT_FIELDS} FROM products WHERE code = ?",
        (code,),
    ).fetchone()


def update_product(
    conn: sqlite3.Connection,
    product_id: int,
    code: str,
    name: str,
    quantity: float,
    unit: str,
    description: str = "",
    weight_kg: float = 1.0,
    group_id: int | None = None,
) -> None:
    """Update a position's main fields (everything except its nutrition).

    The position's code may change freely: nested codes reference positions by
    id, so a rename is reflected automatically and never orphans the recipes
    that use this position.

    If the position's quantity changes, its nested codes are scaled by the same
    factor: a nested quantity is the amount needed for the position's *current*
    quantity, so doubling the position doubles each nested code. Scaling needs a
    non-zero starting quantity to define the factor; from zero it is skipped.
    """
    _check_unit(unit)
    quantity = _round_qty(quantity)
    old = get_product(conn, product_id)
    conn.execute(
        """
        UPDATE products
        SET code = ?, name = ?, quantity = ?, unit = ?, description = ?,
            weight_kg = ?, group_id = ?
        WHERE id = ?
        """,
        (
            code, name, quantity, unit, description, _round_qty(weight_kg),
            group_id, product_id,
        ),
    )
    if old is not None and old["quantity"] > 0 and quantity != old["quantity"]:
        factor = quantity / old["quantity"]
        conn.execute(
            f"""
            UPDATE components
            SET quantity = ROUND(quantity * ?, {QUANTITY_DECIMALS})
            WHERE parent_product_id = ?
            """,
            (factor, product_id),
        )
    conn.commit()


def update_nutrition(
    conn: sqlite3.Connection,
    product_id: int,
    fat: float,
    saturated_fat: float,
    carbs: float,
    sugar: float,
    protein: float,
    salt: float,
) -> None:
    """Set a position's nutrition values (grams per 100 g of product)."""
    conn.execute(
        """
        UPDATE products
        SET fat = ?, saturated_fat = ?, carbs = ?, sugar = ?, protein = ?, salt = ?
        WHERE id = ?
        """,
        (
            _round_qty(fat),
            _round_qty(saturated_fat),
            _round_qty(carbs),
            _round_qty(sugar),
            _round_qty(protein),
            _round_qty(salt),
            product_id,
        ),
    )
    conn.commit()


def delete_product(conn: sqlite3.Connection, product_id: int) -> None:
    """Delete a position and (via cascade) all of its nested codes."""
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()


def set_product_group(
    conn: sqlite3.Connection, product_id: int, group_id: int | None
) -> None:
    """Move a position into a group (or out of any group when ``None``)."""
    conn.execute(
        "UPDATE products SET group_id = ? WHERE id = ?", (group_id, product_id)
    )
    conn.commit()


def set_show_computed(
    conn: sqlite3.Connection, product_id: int, show: bool
) -> None:
    """Remember whether this position's card opens with the computed panel shown."""
    conn.execute(
        "UPDATE products SET show_computed = ? WHERE id = ?",
        (1 if show else 0, product_id),
    )
    conn.commit()


# ----- groups ----------------------------------------------------------


def add_group(conn: sqlite3.Connection, name: str) -> int:
    """Create a product group and return its new row id."""
    name = name.strip()
    if not name:
        raise ValueError("group name must not be empty")
    cur = conn.execute("INSERT INTO groups (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def list_groups(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all groups, ordered by name."""
    return conn.execute("SELECT id, name FROM groups ORDER BY name").fetchall()


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    """Delete a group; its positions become ungrouped (group_id set to NULL)."""
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()


# ----- nested codes (components) ---------------------------------------


def _reaches(conn: sqlite3.Connection, start_id: int, target_id: int) -> bool:
    """True if ``target_id`` can be reached from ``start_id`` by following nested
    codes. Used to reject cycles (e.g. A→B→A) before they are created."""
    seen: set[int] = set()
    stack = [start_id]
    while stack:
        node = stack.pop()
        if node == target_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        for row in conn.execute(
            "SELECT child_product_id FROM components WHERE parent_product_id = ?",
            (node,),
        ):
            stack.append(row["child_product_id"])
    return False


def add_component(
    conn: sqlite3.Connection,
    parent_product_id: int,
    child_product_id: int,
    quantity: float,
) -> int:
    """Nest a position under another and return the new row id.

    ``child_product_id`` is the id of the position to nest; its code, name and
    unit are read live from that position (see :func:`list_components`). Raises
    :class:`ValueError` if the child does not exist, is the parent itself, or
    nesting it would create a cycle (e.g. A→B→A).
    """
    if get_product(conn, child_product_id) is None:
        raise ValueError(f"no position with id {child_product_id!r}")
    if child_product_id == parent_product_id:
        raise ValueError("a position cannot be nested inside itself")
    if _reaches(conn, child_product_id, parent_product_id):
        raise ValueError("nesting this position here would create a cycle")
    cur = conn.execute(
        """
        INSERT INTO components (parent_product_id, child_product_id, quantity)
        VALUES (?, ?, ?)
        """,
        (parent_product_id, child_product_id, _round_qty(quantity)),
    )
    conn.commit()
    return cur.lastrowid


def list_components(
    conn: sqlite3.Connection, parent_product_id: int
) -> list[sqlite3.Row]:
    """Return the positions nested under one position, ordered by child code.

    Each row carries the child's ``child_code``, ``child_name`` and ``unit``
    looked up live from the referenced position, plus ``child_product_id``. So
    editing a position's code or unit is reflected by every nesting of it.
    """
    return conn.execute(
        """
        SELECT c.id, c.child_product_id, p.code AS child_code,
               p.name AS child_name, c.quantity, p.unit AS unit
        FROM components c
        JOIN products p ON p.id = c.child_product_id
        WHERE c.parent_product_id = ?
        ORDER BY p.code
        """,
        (parent_product_id,),
    ).fetchall()


def update_component(
    conn: sqlite3.Connection,
    component_id: int,
    quantity: float,
) -> None:
    """Update the quantity of an existing nested code.

    Only the quantity is per-nesting. The unit comes from the referenced
    position (change it there), and the referenced position is fixed: to point a
    nested entry at a different position, delete it and add a new one.
    """
    conn.execute(
        "UPDATE components SET quantity = ? WHERE id = ?",
        (_round_qty(quantity), component_id),
    )
    conn.commit()


def delete_component(conn: sqlite3.Connection, component_id: int) -> None:
    """Delete a single nested code by its id."""
    conn.execute("DELETE FROM components WHERE id = ?", (component_id,))
    conn.commit()


# ----- computed nutrition ----------------------------------------------


def position_mass_grams(weight_kg: float, quantity: float) -> float:
    """Declared mass of a position in grams: weight per unit x units x 1000.

    A ``kg`` position has ``weight_kg`` forced to 1, so its mass is its quantity
    in kilograms; a ``gab.`` position weighs ``weight_kg`` per piece. A quantity
    of 0 is treated as one unit, so a recipe defined at quantity 0 (a template,
    not stock) still has a per-100 g basis.
    """
    units = quantity if quantity and quantity > 0 else 1
    return float(weight_kg) * float(units) * 1000.0


def recipe_nutrient_grams(
    conn: sqlite3.Connection,
    product_id: int,
    _visiting: frozenset[int] = frozenset(),
) -> dict[str, float] | None:
    """Total grams of each nutrient a position's nested codes contribute.

    Returns ``None`` for a *raw* position (no nested codes) or one already being
    visited (a cycle) — neither has a rolled-up total. Otherwise returns, summed
    over every nested code, ``ingredient_mass_g / 100 * ingredient_per100g``,
    where each ingredient's per-100 g is itself :func:`effective_nutrition` (so
    sub-recipes recurse). A nested code's mass in grams is
    ``quantity * child.weight_kg * 1000`` (a ``kg`` child is 1 kg/unit, a ``gab.``
    child uses its per-piece weight).

    This is the *numerator* of the per-100 g roll-up; :func:`effective_nutrition`
    divides it by the position's own declared mass.
    """
    if product_id in _visiting:
        return None
    components = list_components(conn, product_id)
    if not components:
        return None
    visiting = _visiting | {product_id}
    totals = {n: 0.0 for n in NUTRIENTS}
    for comp in components:
        child = get_product(conn, comp["child_product_id"])
        if child is None:
            continue
        grams = float(comp["quantity"]) * float(child["weight_kg"]) * 1000.0
        if grams <= 0:
            continue
        child_nutrition = effective_nutrition(conn, child["id"], visiting)
        for n in NUTRIENTS:
            totals[n] += grams / 100.0 * child_nutrition[n]
    return totals


def effective_nutrition(
    conn: sqlite3.Connection,
    product_id: int,
    _visiting: frozenset[int] = frozenset(),
) -> dict[str, float]:
    """Nutrition per 100 g of a position, as a dict over :data:`NUTRIENTS`.

    A position made of nested codes is a recipe: its per-100 g is the nutrients
    its ingredients contribute (:func:`recipe_nutrient_grams`) divided by the
    position's **own declared mass** (:func:`position_mass_grams`), times 100. So
    a 1 kg position holding 2 kg of an ingredient is twice as concentrated as
    that ingredient — the position's weight, not the ingredient total, is the
    100 g basis. The roll-up recurses into sub-recipes and is cycle-safe.

    A raw position (no nested codes) returns its own stored per-100 g values.
    """
    row = get_product(conn, product_id)
    if row is None:
        return {n: 0.0 for n in NUTRIENTS}
    totals = recipe_nutrient_grams(conn, product_id, _visiting)
    if totals is None:
        # Raw ingredient (or a cycle): use the stored per-100 g values.
        return {n: float(row[n]) for n in NUTRIENTS}
    basis = position_mass_grams(row["weight_kg"], row["quantity"])
    if basis <= 0:
        return {n: 0.0 for n in NUTRIENTS}
    return {n: totals[n] / basis * 100.0 for n in NUTRIENTS}

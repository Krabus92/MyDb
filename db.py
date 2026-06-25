"""SQLite data layer for MyDb.

Holds two tables:

* ``products``   — one row per position (code, name, quantity, unit)
* ``components`` — codes nested under a position, each with its own quantity

A nested code refers to *another position* by its ``code``. The position's name
is not copied into the components table; it is looked up by joining back to
``products`` (see :func:`list_components`), so a nested code always shows the
current name of the position it points to.

The GUI in :mod:`app` talks to the database only through the helpers here, so
the storage logic stays in one place and is easy to test.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Default location of the database file (next to this module).
DB_PATH = Path(__file__).with_name("mydb.sqlite3")

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
            group_id      INTEGER REFERENCES groups (id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS components (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_product_id INTEGER NOT NULL,
            child_code        TEXT NOT NULL,
            quantity          REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (parent_product_id)
                REFERENCES products (id) ON DELETE CASCADE
        );
        """
    )
    _migrate_drop_component_unit(conn)
    _migrate_add_product_columns(conn)
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
    "fat, saturated_fat, carbs, sugar, protein, salt, group_id"
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


def add_component(
    conn: sqlite3.Connection,
    parent_product_id: int,
    child_code: str,
    quantity: float,
) -> int:
    """Nest a code under a position and return its new row id.

    ``child_code`` must be the code of an existing position (other than the
    parent itself), since the nested code's name *and unit* are taken from that
    position. Raises :class:`ValueError` if no position uses that code or if the
    code refers to the parent position.
    """
    child = find_product_by_code(conn, child_code)
    if child is None:
        raise ValueError(f"no position has code {child_code!r}")
    if child["id"] == parent_product_id:
        raise ValueError("a position cannot be nested inside itself")
    cur = conn.execute(
        """
        INSERT INTO components (parent_product_id, child_code, quantity)
        VALUES (?, ?, ?)
        """,
        (parent_product_id, child_code, _round_qty(quantity)),
    )
    conn.commit()
    return cur.lastrowid


def list_components(
    conn: sqlite3.Connection, parent_product_id: int
) -> list[sqlite3.Row]:
    """Return the codes nested under one position, ordered by child code.

    Each row includes ``child_name`` and ``unit`` looked up from the referenced
    position (both ``None`` if that position has since been deleted), so editing
    a position's unit is reflected by every nesting of it.
    """
    return conn.execute(
        """
        SELECT c.id, c.child_code, p.name AS child_name, c.quantity, p.unit AS unit
        FROM components c
        LEFT JOIN products p ON p.code = c.child_code
        WHERE c.parent_product_id = ?
        ORDER BY c.child_code
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
    position (change it there), and the ``child_code`` reference is fixed: to
    point a nested entry at a different position, delete it and add a new one.
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

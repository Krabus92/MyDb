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
    """Create the tables if they do not already exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            code     TEXT NOT NULL UNIQUE,
            name     TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 0,
            unit     TEXT NOT NULL CHECK (unit IN ('gab.', 'kg'))
        );

        CREATE TABLE IF NOT EXISTS components (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_product_id INTEGER NOT NULL,
            child_code        TEXT NOT NULL,
            quantity          REAL NOT NULL DEFAULT 0,
            unit              TEXT NOT NULL CHECK (unit IN ('gab.', 'kg')),
            FOREIGN KEY (parent_product_id)
                REFERENCES products (id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()


def _check_unit(unit: str) -> None:
    if unit not in VALID_UNITS:
        raise ValueError(f"unit must be one of {VALID_UNITS}, got {unit!r}")


# ----- positions (products) --------------------------------------------


def add_product(
    conn: sqlite3.Connection,
    code: str,
    name: str,
    quantity: float,
    unit: str,
) -> int:
    """Insert a position and return its new row id."""
    _check_unit(unit)
    cur = conn.execute(
        "INSERT INTO products (code, name, quantity, unit) VALUES (?, ?, ?, ?)",
        (code, name, quantity, unit),
    )
    conn.commit()
    return cur.lastrowid


def list_products(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all positions, ordered by code."""
    return conn.execute(
        "SELECT id, code, name, quantity, unit FROM products ORDER BY code"
    ).fetchall()


def get_product(conn: sqlite3.Connection, product_id: int) -> sqlite3.Row | None:
    """Return one position by id, or ``None`` if it does not exist."""
    return conn.execute(
        "SELECT id, code, name, quantity, unit FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()


def find_product_by_code(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    """Return one position by its code, or ``None`` if no position uses it."""
    return conn.execute(
        "SELECT id, code, name, quantity, unit FROM products WHERE code = ?",
        (code,),
    ).fetchone()


def update_product(
    conn: sqlite3.Connection,
    product_id: int,
    code: str,
    name: str,
    quantity: float,
    unit: str,
) -> None:
    """Update every field of an existing position."""
    _check_unit(unit)
    conn.execute(
        """
        UPDATE products
        SET code = ?, name = ?, quantity = ?, unit = ?
        WHERE id = ?
        """,
        (code, name, quantity, unit, product_id),
    )
    conn.commit()


def delete_product(conn: sqlite3.Connection, product_id: int) -> None:
    """Delete a position and (via cascade) all of its nested codes."""
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()


# ----- nested codes (components) ---------------------------------------


def add_component(
    conn: sqlite3.Connection,
    parent_product_id: int,
    child_code: str,
    quantity: float,
    unit: str,
) -> int:
    """Nest a code under a position and return its new row id.

    ``child_code`` must be the code of an existing position (other than the
    parent itself), since the nested code's name is taken from that position.
    Raises :class:`ValueError` if no position uses that code or if the code
    refers to the parent position.
    """
    _check_unit(unit)
    child = find_product_by_code(conn, child_code)
    if child is None:
        raise ValueError(f"no position has code {child_code!r}")
    if child["id"] == parent_product_id:
        raise ValueError("a position cannot be nested inside itself")
    cur = conn.execute(
        """
        INSERT INTO components (parent_product_id, child_code, quantity, unit)
        VALUES (?, ?, ?, ?)
        """,
        (parent_product_id, child_code, quantity, unit),
    )
    conn.commit()
    return cur.lastrowid


def list_components(
    conn: sqlite3.Connection, parent_product_id: int
) -> list[sqlite3.Row]:
    """Return the codes nested under one position, ordered by child code.

    Each row includes ``child_name`` looked up from the referenced position
    (``None`` if that position has since been deleted).
    """
    return conn.execute(
        """
        SELECT c.id, c.child_code, p.name AS child_name, c.quantity, c.unit
        FROM components c
        LEFT JOIN products p ON p.code = c.child_code
        WHERE c.parent_product_id = ?
        ORDER BY c.child_code
        """,
        (parent_product_id,),
    ).fetchall()


def delete_component(conn: sqlite3.Connection, component_id: int) -> None:
    """Delete a single nested code by its id."""
    conn.execute("DELETE FROM components WHERE id = ?", (component_id,))
    conn.commit()

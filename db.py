"""SQLite data layer for MyDb.

Holds two tables:

* ``products``   — one row per product (code, name, quantity, unit)
* ``components`` — codes nested under a product, each with its own quantity

The GUI in :mod:`app` talks to the database only through the helpers here, so
the storage logic stays in one place and is easy to test.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Default location of the database file (next to this module).
DB_PATH = Path(__file__).with_name("mydb.sqlite3")

#: The only units a product or component may use.
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


def add_product(
    conn: sqlite3.Connection,
    code: str,
    name: str,
    quantity: float,
    unit: str,
) -> int:
    """Insert a product and return its new row id."""
    if unit not in VALID_UNITS:
        raise ValueError(f"unit must be one of {VALID_UNITS}, got {unit!r}")
    cur = conn.execute(
        "INSERT INTO products (code, name, quantity, unit) VALUES (?, ?, ?, ?)",
        (code, name, quantity, unit),
    )
    conn.commit()
    return cur.lastrowid


def list_products(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all products, ordered by code."""
    return conn.execute(
        "SELECT id, code, name, quantity, unit FROM products ORDER BY code"
    ).fetchall()


def add_component(
    conn: sqlite3.Connection,
    parent_product_id: int,
    child_code: str,
    quantity: float,
    unit: str,
) -> int:
    """Nest a component code under a product and return its new row id."""
    if unit not in VALID_UNITS:
        raise ValueError(f"unit must be one of {VALID_UNITS}, got {unit!r}")
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
    """Return the components nested under one product, ordered by child code."""
    return conn.execute(
        """
        SELECT id, child_code, quantity, unit
        FROM components
        WHERE parent_product_id = ?
        ORDER BY child_code
        """,
        (parent_product_id,),
    ).fetchall()

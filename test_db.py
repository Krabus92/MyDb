"""Tests for the :mod:`db` data layer.

Each test uses a fresh in-memory SQLite database, so nothing touches the real
``mydb.sqlite3`` file. Run them with::

    python -m unittest
"""

import unittest

import db


class DbLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        # ":memory:" gives every test its own throwaway database.
        self.conn = db.get_connection(":memory:")
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    # ----- positions ----------------------------------------------------

    def test_add_and_list_product(self) -> None:
        product_id = db.add_product(self.conn, "A-100", "Widget", 5, "gab.")
        self.assertIsInstance(product_id, int)

        products = db.list_products(self.conn)
        self.assertEqual(len(products), 1)
        row = products[0]
        self.assertEqual(row["code"], "A-100")
        self.assertEqual(row["name"], "Widget")
        self.assertEqual(row["quantity"], 5)
        self.assertEqual(row["unit"], "gab.")

    def test_products_listed_in_code_order(self) -> None:
        db.add_product(self.conn, "B-200", "Second", 1, "kg")
        db.add_product(self.conn, "A-100", "First", 1, "gab.")
        codes = [row["code"] for row in db.list_products(self.conn)]
        self.assertEqual(codes, ["A-100", "B-200"])

    def test_invalid_unit_rejected(self) -> None:
        with self.assertRaises(ValueError):
            db.add_product(self.conn, "X-1", "Bad unit", 1, "litres")

    def test_get_and_find_product(self) -> None:
        product_id = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        self.assertEqual(db.get_product(self.conn, product_id)["name"], "Widget")
        self.assertEqual(db.find_product_by_code(self.conn, "A-100")["id"], product_id)
        self.assertIsNone(db.get_product(self.conn, 999))
        self.assertIsNone(db.find_product_by_code(self.conn, "nope"))

    def test_update_product(self) -> None:
        product_id = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.update_product(self.conn, product_id, "A-101", "Gadget", 9, "kg")
        row = db.get_product(self.conn, product_id)
        self.assertEqual(row["code"], "A-101")
        self.assertEqual(row["name"], "Gadget")
        self.assertEqual(row["quantity"], 9)
        self.assertEqual(row["unit"], "kg")

    def test_update_product_rejects_invalid_unit(self) -> None:
        product_id = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        with self.assertRaises(ValueError):
            db.update_product(self.conn, product_id, "A-100", "Widget", 1, "litres")

    def test_update_product_scales_nested_quantities(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_product(self.conn, "C-300", "Resin", 0, "kg")
        db.add_component(self.conn, parent, "B-200", 1)
        db.add_component(self.conn, parent, "C-300", 2.5)

        # Doubling the position's quantity (1 -> 2) doubles every nested code.
        db.update_product(self.conn, parent, "A-100", "Widget", 2, "gab.")

        comps = {c["child_code"]: c["quantity"] for c in db.list_components(self.conn, parent)}
        self.assertEqual(comps["B-200"], 2)
        self.assertEqual(comps["C-300"], 5)

    def test_update_product_scales_down_and_rounds(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 3, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_component(self.conn, parent, "B-200", 1)

        # 3 -> 1 is a factor of 1/3; 1 * 1/3 rounds to 0.333.
        db.update_product(self.conn, parent, "A-100", "Widget", 1, "gab.")
        self.assertEqual(db.list_components(self.conn, parent)[0]["quantity"], 0.333)

    def test_update_product_without_quantity_change_leaves_nested(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 2, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_component(self.conn, parent, "B-200", 5)

        # Only the name changes; quantity stays 2, so nested codes are untouched.
        db.update_product(self.conn, parent, "A-100", "Renamed", 2, "gab.")
        self.assertEqual(db.list_components(self.conn, parent)[0]["quantity"], 5)

    def test_update_product_from_zero_quantity_skips_scaling(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 0, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_component(self.conn, parent, "B-200", 5)

        # No baseline to scale from (0 -> 4), so nested codes are left as-is.
        db.update_product(self.conn, parent, "A-100", "Widget", 4, "gab.")
        self.assertEqual(db.list_components(self.conn, parent)[0]["quantity"], 5)

    def test_quantities_rounded_to_three_decimals(self) -> None:
        pid = db.add_product(self.conn, "A-100", "Widget", 1.23456, "gab.")
        self.assertEqual(db.get_product(self.conn, pid)["quantity"], 1.235)

        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        comp_id = db.add_component(self.conn, pid, "B-200", 0.12345)
        self.assertEqual(db.list_components(self.conn, pid)[0]["quantity"], 0.123)

        db.update_component(self.conn, comp_id, 9.87654)
        self.assertEqual(db.list_components(self.conn, pid)[0]["quantity"], 9.877)

    def test_delete_product_cascades_to_components(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 1, "gab.")
        db.add_component(self.conn, parent, "B-200", 5)

        db.delete_product(self.conn, parent)
        self.assertIsNone(db.get_product(self.conn, parent))
        self.assertEqual(db.list_components(self.conn, parent), [])

    # ----- nested codes -------------------------------------------------

    def test_add_and_list_components_with_resolved_name_and_unit(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_product(self.conn, "C-300", "Resin", 0, "kg")
        db.add_component(self.conn, parent, "B-200", 5)
        db.add_component(self.conn, parent, "C-300", 2.3)

        components = db.list_components(self.conn, parent)
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0]["child_code"], "B-200")
        self.assertEqual(components[0]["child_name"], "Bolt")
        self.assertEqual(components[0]["unit"], "gab.")  # resolved from B-200
        self.assertEqual(components[1]["child_name"], "Resin")
        self.assertEqual(components[1]["quantity"], 2.3)
        self.assertEqual(components[1]["unit"], "kg")  # resolved from C-300

    def test_nested_unit_follows_referenced_position(self) -> None:
        # The headline rule: a nested code's unit is the position's unit, so
        # changing it on the position updates every nesting of that position.
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "kg")
        db.add_component(self.conn, parent, "B-200", 5)
        self.assertEqual(db.list_components(self.conn, parent)[0]["unit"], "kg")

        db.update_product(self.conn, bolt, "B-200", "Bolt", 0, "gab.")
        self.assertEqual(db.list_components(self.conn, parent)[0]["unit"], "gab.")

    def test_nested_code_must_reference_existing_position(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        with self.assertRaises(ValueError):
            db.add_component(self.conn, parent, "DOES-NOT-EXIST", 1)

    def test_position_cannot_nest_itself(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        with self.assertRaises(ValueError):
            db.add_component(self.conn, parent, "A-100", 1)

    def test_update_component_changes_only_quantity(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "kg")
        comp_id = db.add_component(self.conn, parent, "B-200", 5)

        db.update_component(self.conn, comp_id, 12)

        comp = db.list_components(self.conn, parent)[0]
        self.assertEqual(comp["quantity"], 12)
        self.assertEqual(comp["unit"], "kg")  # still the position's unit
        self.assertEqual(comp["child_code"], "B-200")  # reference unchanged

    def test_delete_component(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        comp_id = db.add_component(self.conn, parent, "B-200", 5)

        db.delete_component(self.conn, comp_id)
        self.assertEqual(db.list_components(self.conn, parent), [])

    def test_components_isolated_per_product(self) -> None:
        first = db.add_product(self.conn, "A-100", "First", 1, "gab.")
        second = db.add_product(self.conn, "B-200", "Second", 1, "gab.")
        db.add_product(self.conn, "C-300", "Child", 0, "gab.")
        db.add_component(self.conn, first, "C-300", 1)

        self.assertEqual(len(db.list_components(self.conn, first)), 1)
        self.assertEqual(len(db.list_components(self.conn, second)), 0)

    def test_init_db_migrates_away_old_component_unit_column(self) -> None:
        # Simulate a pre-migration database that still stores a unit per code.
        conn = db.get_connection(":memory:")
        conn.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL CHECK (unit IN ('gab.', 'kg'))
            );
            CREATE TABLE components (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_product_id INTEGER NOT NULL,
                child_code TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT 'kg',
                FOREIGN KEY (parent_product_id)
                    REFERENCES products (id) ON DELETE CASCADE
            );
            INSERT INTO products (code, name, quantity, unit)
                VALUES ('A-100', 'Widget', 1, 'gab.');
            INSERT INTO components (parent_product_id, child_code, quantity, unit)
                VALUES (1, 'B-200', 5, 'kg');
            """
        )
        conn.commit()

        db.init_db(conn)  # should drop components.unit but keep the data

        columns = [r["name"] for r in conn.execute("PRAGMA table_info(components)")]
        self.assertNotIn("unit", columns)
        row = conn.execute(
            "SELECT child_code, quantity FROM components"
        ).fetchone()
        self.assertEqual(row["child_code"], "B-200")
        self.assertEqual(row["quantity"], 5)
        conn.close()


if __name__ == "__main__":
    unittest.main()

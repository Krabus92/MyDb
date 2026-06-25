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

    def test_delete_product_cascades_to_components(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 1, "gab.")
        db.add_component(self.conn, parent, "B-200", 5, "gab.")

        db.delete_product(self.conn, parent)
        self.assertIsNone(db.get_product(self.conn, parent))
        self.assertEqual(db.list_components(self.conn, parent), [])

    # ----- nested codes -------------------------------------------------

    def test_add_and_list_components_with_resolved_name(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_product(self.conn, "C-300", "Resin", 0, "kg")
        db.add_component(self.conn, parent, "B-200", 5, "gab.")
        db.add_component(self.conn, parent, "C-300", 2.3, "kg")

        components = db.list_components(self.conn, parent)
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0]["child_code"], "B-200")
        self.assertEqual(components[0]["child_name"], "Bolt")
        self.assertEqual(components[1]["child_name"], "Resin")
        self.assertEqual(components[1]["quantity"], 2.3)

    def test_nested_code_must_reference_existing_position(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        with self.assertRaises(ValueError):
            db.add_component(self.conn, parent, "DOES-NOT-EXIST", 1, "gab.")

    def test_position_cannot_nest_itself(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        with self.assertRaises(ValueError):
            db.add_component(self.conn, parent, "A-100", 1, "gab.")

    def test_delete_component(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        comp_id = db.add_component(self.conn, parent, "B-200", 5, "gab.")

        db.delete_component(self.conn, comp_id)
        self.assertEqual(db.list_components(self.conn, parent), [])

    def test_components_isolated_per_product(self) -> None:
        first = db.add_product(self.conn, "A-100", "First", 1, "gab.")
        second = db.add_product(self.conn, "B-200", "Second", 1, "gab.")
        db.add_product(self.conn, "C-300", "Child", 0, "gab.")
        db.add_component(self.conn, first, "C-300", 1, "gab.")

        self.assertEqual(len(db.list_components(self.conn, first)), 1)
        self.assertEqual(len(db.list_components(self.conn, second)), 0)


if __name__ == "__main__":
    unittest.main()

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

    def test_add_and_list_components(self) -> None:
        parent_id = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        db.add_component(self.conn, parent_id, "B-200", 5, "gab.")
        db.add_component(self.conn, parent_id, "C-300", 2.3, "kg")

        components = db.list_components(self.conn, parent_id)
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0]["child_code"], "B-200")
        self.assertEqual(components[1]["child_code"], "C-300")
        self.assertEqual(components[1]["quantity"], 2.3)

    def test_components_isolated_per_product(self) -> None:
        first = db.add_product(self.conn, "A-100", "First", 1, "gab.")
        second = db.add_product(self.conn, "B-200", "Second", 1, "gab.")
        db.add_component(self.conn, first, "C-300", 1, "gab.")

        self.assertEqual(len(db.list_components(self.conn, first)), 1)
        self.assertEqual(len(db.list_components(self.conn, second)), 0)


if __name__ == "__main__":
    unittest.main()

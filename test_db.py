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

    def test_product_description_defaults_empty_and_persists(self) -> None:
        pid = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        self.assertEqual(db.get_product(self.conn, pid)["description"], "")

        notes = "Mīkla ar ļoti garu aprakstu.\nOtrā rinda."
        db.update_product(self.conn, pid, "A-100", "Widget", 1, "gab.", notes)
        self.assertEqual(db.get_product(self.conn, pid)["description"], notes)

    def test_add_product_with_description(self) -> None:
        pid = db.add_product(self.conn, "A-100", "Widget", 1, "gab.", "a note")
        self.assertEqual(db.get_product(self.conn, pid)["description"], "a note")

    def test_show_computed_defaults_off_and_persists(self) -> None:
        pid = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        self.assertEqual(db.get_product(self.conn, pid)["show_computed"], 0)

        db.set_show_computed(self.conn, pid, True)
        self.assertEqual(db.get_product(self.conn, pid)["show_computed"], 1)
        db.set_show_computed(self.conn, pid, False)
        self.assertEqual(db.get_product(self.conn, pid)["show_computed"], 0)

    def test_init_db_adds_missing_description_column(self) -> None:
        # Simulate a database created before the description column existed.
        conn = db.get_connection(":memory:")
        conn.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL CHECK (unit IN ('gab.', 'kg'))
            );
            INSERT INTO products (code, name, quantity, unit)
                VALUES ('A-100', 'Widget', 1, 'gab.');
            """
        )
        conn.commit()

        db.init_db(conn)

        columns = [r["name"] for r in conn.execute("PRAGMA table_info(products)")]
        self.assertIn("description", columns)
        self.assertEqual(db.find_product_by_code(conn, "A-100")["description"], "")
        conn.close()

    # ----- weight & nutrition -------------------------------------------

    def test_weight_defaults_to_one_and_persists(self) -> None:
        pid = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        self.assertEqual(db.get_product(self.conn, pid)["weight_kg"], 1)

        with_w = db.add_product(self.conn, "B-200", "Bolt", 1, "gab.", "", 0.25)
        self.assertEqual(db.get_product(self.conn, with_w)["weight_kg"], 0.25)

        db.update_product(self.conn, pid, "A-100", "Widget", 1, "gab.", "", 0.5)
        self.assertEqual(db.get_product(self.conn, pid)["weight_kg"], 0.5)

    def test_nutrition_defaults_zero_and_persists(self) -> None:
        pid = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        row = db.get_product(self.conn, pid)
        for field in ("fat", "saturated_fat", "carbs", "sugar", "protein", "salt"):
            self.assertEqual(row[field], 0)

        db.update_nutrition(self.conn, pid, 10, 3, 20, 5, 8, 1.2)
        row = db.get_product(self.conn, pid)
        self.assertEqual(row["fat"], 10)
        self.assertEqual(row["saturated_fat"], 3)
        self.assertEqual(row["carbs"], 20)
        self.assertEqual(row["sugar"], 5)
        self.assertEqual(row["protein"], 8)
        self.assertEqual(row["salt"], 1.2)

    def test_energy_from_macros(self) -> None:
        # 1 g fat = 9 kcal, 1 g carbs = 4 kcal, 1 g protein = 4 kcal.
        self.assertEqual(db.energy_kcal(10, 20, 5), 10 * 9 + 20 * 4 + 5 * 4)
        self.assertEqual(db.energy_kcal(10, 20, 5), 190)
        self.assertAlmostEqual(db.energy_kj(10, 20, 5), 190 * 4.184)

    # ----- computed nutrition (roll-up from nested positions) -----------

    def test_effective_nutrition_raw_uses_stored(self) -> None:
        pid = db.add_product(self.conn, "A-100", "Flour", 1, "kg")
        db.update_nutrition(self.conn, pid, 1, 0.2, 70, 1, 10, 0.01)
        n = db.effective_nutrition(self.conn, pid)
        self.assertEqual(n["fat"], 1)
        self.assertEqual(n["carbs"], 70)
        self.assertEqual(n["protein"], 10)

    def test_effective_nutrition_divides_by_declared_mass(self) -> None:
        # The 100 g basis is the position's OWN declared mass (1 kg here), not
        # the ingredient total: 2 kg of butter in a 1 kg position is 2x butter.
        a = db.add_product(self.conn, "A-100", "Recipe", 1, "kg")  # 1 kg basis
        b = db.add_product(self.conn, "B-200", "Butter", 1, "kg")
        db.update_nutrition(self.conn, b, 80, 50, 1, 0, 1, 1.5)
        db.add_component(self.conn, a, b, 2)  # 2 kg of butter

        n = db.effective_nutrition(self.conn, a)
        self.assertAlmostEqual(n["fat"], 160)          # 2 kg x 80 / 1 kg
        self.assertAlmostEqual(n["saturated_fat"], 100)
        self.assertAlmostEqual(n["protein"], 2)
        self.assertAlmostEqual(n["salt"], 3)

    def test_effective_nutrition_weighted_by_mass(self) -> None:
        a = db.add_product(self.conn, "A-100", "Recipe", 1, "kg")  # 1 kg basis
        b = db.add_product(self.conn, "B-200", "Fatty", 1, "kg")
        c = db.add_product(self.conn, "C-300", "Lean", 1, "kg")
        db.update_nutrition(self.conn, b, 10, 0, 0, 0, 0, 0)   # fat 10/100g
        db.update_nutrition(self.conn, c, 0, 0, 0, 0, 30, 0)   # protein 30/100g
        db.add_component(self.conn, a, b, 1)  # 1 kg = 1000 g
        db.add_component(self.conn, a, c, 1)  # 1 kg = 1000 g

        n = db.effective_nutrition(self.conn, a)
        # 2 kg of ingredients in a 1 kg position: fat 100 g / 1000 g -> 10,
        # protein 300 g / 1000 g -> 30.
        self.assertAlmostEqual(n["fat"], 10)
        self.assertAlmostEqual(n["protein"], 30)

    def test_effective_nutrition_uses_piece_weight_for_gab(self) -> None:
        a = db.add_product(self.conn, "A-100", "Recipe", 1, "kg")  # 1 kg basis
        # An egg: counted in pieces, 0.05 kg each, 11 g fat per 100 g.
        egg = db.add_product(self.conn, "E-1", "Egg", 1, "gab.", "", 0.05)
        db.update_nutrition(self.conn, egg, 11, 3, 1, 1, 13, 0.3)
        db.add_component(self.conn, a, egg, 4)  # 4 eggs = 200 g in a 1000 g basis

        n = db.effective_nutrition(self.conn, a)
        self.assertAlmostEqual(n["fat"], 2.2)    # 200 g x 11 / 1000 g
        self.assertAlmostEqual(n["protein"], 2.6)

    def test_effective_nutrition_concentrates_a_gab_subrecipe(self) -> None:
        # The user's "test 4" case: a 1 kg piece holding 2 kg of a sub-recipe is
        # twice as concentrated as that sub-recipe, two levels deep.
        t1 = db.add_product(self.conn, "0001", "t1", 0, "kg")
        db.update_nutrition(self.conn, t1, 15, 0, 20, 0, 0, 0)   # fat 15, carbs 20
        t2 = db.add_product(self.conn, "0002", "t2", 0, "kg")
        db.update_nutrition(self.conn, t2, 0, 0, 15, 0, 20, 0)   # carbs 15, protein 20
        t3 = db.add_product(self.conn, "0003", "t3", 0, "gab.", "", 1.0)  # 1 kg/piece
        db.add_component(self.conn, t3, t1, 0.3)   # 0.3 kg t1
        db.add_component(self.conn, t3, t2, 0.7)   # 0.7 kg t2 -> 1 kg total = basis
        t4 = db.add_product(self.conn, "0004", "t4", 1, "gab.", "", 1.0)  # 1 kg/piece
        db.add_component(self.conn, t4, t3, 2)     # 2 pieces (2 kg) of t3

        n3 = db.effective_nutrition(self.conn, t3)
        self.assertAlmostEqual(n3["fat"], 4.5)
        self.assertAlmostEqual(n3["carbs"], 16.5)
        self.assertAlmostEqual(n3["protein"], 14.0)

        n4 = db.effective_nutrition(self.conn, t4)  # 2 kg of t3 in a 1 kg piece -> 2x
        self.assertAlmostEqual(n4["fat"], 9.0)
        self.assertAlmostEqual(n4["carbs"], 33.0)
        self.assertAlmostEqual(n4["protein"], 28.0)

    def test_effective_nutrition_is_quantity_invariant(self) -> None:
        # Per 100 g is a concentration: making more (quantity up, nested codes
        # scaled to match) must not change it.
        r = db.add_product(self.conn, "A-100", "Recipe", 1, "kg")
        b = db.add_product(self.conn, "B-200", "Butter", 1, "kg")
        db.update_nutrition(self.conn, b, 80, 0, 0, 0, 0, 0)
        db.add_component(self.conn, r, b, 1)
        before = db.effective_nutrition(self.conn, r)["fat"]  # 1 kg butter / 1 kg

        # quantity 1 -> 2 scales the nested butter 1 -> 2 kg; basis also doubles.
        db.update_product(self.conn, r, "A-100", "Recipe", 2, "kg")
        after = db.effective_nutrition(self.conn, r)["fat"]
        self.assertAlmostEqual(before, 80.0)
        self.assertAlmostEqual(after, 80.0)

    def test_effective_nutrition_recurses_through_subrecipes(self) -> None:
        base = db.add_product(self.conn, "C-300", "Oil", 1, "kg")
        db.update_nutrition(self.conn, base, 100, 14, 0, 0, 0, 0)  # pure fat
        mid = db.add_product(self.conn, "B-200", "Dressing", 1, "kg")
        db.add_component(self.conn, mid, base, 1)  # 1 kg Oil in a 1 kg Dressing
        top = db.add_product(self.conn, "A-100", "Salad", 1, "kg")
        db.add_component(self.conn, top, mid, 1)  # 1 kg Dressing in a 1 kg Salad

        n = db.effective_nutrition(self.conn, top)
        self.assertAlmostEqual(n["fat"], 100)  # 1:1 masses pass concentration through

    def test_position_mass_grams(self) -> None:
        self.assertEqual(db.position_mass_grams(1, 1), 1000)      # 1 kg
        self.assertEqual(db.position_mass_grams(0.05, 4), 200)    # 4 pieces of 50 g
        self.assertEqual(db.position_mass_grams(1, 0), 1000)      # qty 0 -> one unit
        self.assertEqual(db.position_mass_grams(2, 3), 6000)

    def test_recipe_nutrient_grams_none_for_raw(self) -> None:
        raw = db.add_product(self.conn, "A-100", "Flour", 1, "kg")
        db.update_nutrition(self.conn, raw, 1, 0, 70, 0, 10, 0)
        self.assertIsNone(db.recipe_nutrient_grams(self.conn, raw))  # raw -> None

        recipe = db.add_product(self.conn, "B-200", "Recipe", 1, "kg")
        db.add_component(self.conn, recipe, raw, 2)  # 2 kg flour = 2000 g
        totals = db.recipe_nutrient_grams(self.conn, recipe)
        self.assertAlmostEqual(totals["fat"], 20)       # 2000 g x 1 / 100
        self.assertAlmostEqual(totals["protein"], 200)  # 2000 g x 10 / 100

    def test_effective_nutrition_is_cycle_safe(self) -> None:
        a = db.add_product(self.conn, "A-100", "A", 1, "kg")
        b = db.add_product(self.conn, "B-200", "B", 1, "kg")
        db.update_nutrition(self.conn, a, 7, 0, 0, 0, 0, 0)
        db.add_component(self.conn, a, b, 1)
        # add_component would reject the back-edge, so insert it directly to
        # prove the roll-up still terminates if a cyclic row ever exists.
        self.conn.execute(
            "INSERT INTO components (parent_product_id, child_product_id, quantity)"
            " VALUES (?, ?, ?)",
            (b, a, 1),
        )
        self.conn.commit()

        n = db.effective_nutrition(self.conn, a)  # must terminate
        self.assertIsInstance(n["fat"], float)

    def test_init_db_adds_missing_weight_and_nutrition_columns(self) -> None:
        # A database created before weight/nutrition columns existed.
        conn = db.get_connection(":memory:")
        conn.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL CHECK (unit IN ('gab.', 'kg'))
            );
            INSERT INTO products (code, name, quantity, unit)
                VALUES ('A-100', 'Widget', 1, 'gab.');
            """
        )
        conn.commit()

        db.init_db(conn)

        columns = [r["name"] for r in conn.execute("PRAGMA table_info(products)")]
        for col in ("weight_kg", "fat", "saturated_fat", "carbs", "sugar",
                    "protein", "salt"):
            self.assertIn(col, columns)
        row = db.find_product_by_code(conn, "A-100")
        self.assertEqual(row["weight_kg"], 1)  # default for migrated rows
        self.assertEqual(row["fat"], 0)
        conn.close()

    # ----- groups -------------------------------------------------------

    def test_add_and_list_groups_ordered_by_name(self) -> None:
        db.add_group(self.conn, "Sauces")
        db.add_group(self.conn, "Breads")
        names = [g["name"] for g in db.list_groups(self.conn)]
        self.assertEqual(names, ["Breads", "Sauces"])

    def test_add_group_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            db.add_group(self.conn, "   ")

    def test_products_filtered_by_group(self) -> None:
        breads = db.add_group(self.conn, "Breads")
        loaf = db.add_product(self.conn, "A-100", "Loaf", 1, "gab.", "", 0.5, breads)
        db.add_product(self.conn, "B-200", "Loose", 1, "kg")  # ungrouped

        in_group = [p["code"] for p in db.list_products(self.conn, breads)]
        self.assertEqual(in_group, ["A-100"])
        all_codes = [p["code"] for p in db.list_products(self.conn)]
        self.assertEqual(all_codes, ["A-100", "B-200"])  # None -> everything
        self.assertEqual(db.get_product(self.conn, loaf)["group_id"], breads)

    def test_set_product_group_moves_position(self) -> None:
        breads = db.add_group(self.conn, "Breads")
        pid = db.add_product(self.conn, "A-100", "Loaf", 1, "gab.")
        self.assertIsNone(db.get_product(self.conn, pid)["group_id"])

        db.set_product_group(self.conn, pid, breads)
        self.assertEqual(db.get_product(self.conn, pid)["group_id"], breads)
        db.set_product_group(self.conn, pid, None)
        self.assertIsNone(db.get_product(self.conn, pid)["group_id"])

    def test_delete_group_ungroups_its_products(self) -> None:
        breads = db.add_group(self.conn, "Breads")
        pid = db.add_product(self.conn, "A-100", "Loaf", 1, "gab.", "", 0.5, breads)

        db.delete_group(self.conn, breads)
        self.assertEqual(db.list_groups(self.conn), [])
        # The position survives but is now ungrouped (FK ON DELETE SET NULL).
        self.assertIsNone(db.get_product(self.conn, pid)["group_id"])

    def test_init_db_adds_groups_and_group_id(self) -> None:
        conn = db.get_connection(":memory:")
        conn.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL CHECK (unit IN ('gab.', 'kg'))
            );
            INSERT INTO products (code, name, quantity, unit)
                VALUES ('A-100', 'Widget', 1, 'gab.');
            """
        )
        conn.commit()

        db.init_db(conn)

        columns = [r["name"] for r in conn.execute("PRAGMA table_info(products)")]
        self.assertIn("group_id", columns)
        self.assertIsNone(db.find_product_by_code(conn, "A-100")["group_id"])
        # The groups table now exists and is usable.
        gid = db.add_group(conn, "Breads")
        self.assertEqual([g["name"] for g in db.list_groups(conn)], ["Breads"])
        conn.close()

    def test_update_product_scales_nested_quantities(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        resin = db.add_product(self.conn, "C-300", "Resin", 0, "kg")
        db.add_component(self.conn, parent, bolt, 1)
        db.add_component(self.conn, parent, resin, 2.5)

        # Doubling the position's quantity (1 -> 2) doubles every nested code.
        db.update_product(self.conn, parent, "A-100", "Widget", 2, "gab.")

        comps = {c["child_code"]: c["quantity"]
                 for c in db.list_components(self.conn, parent)}
        self.assertEqual(comps["B-200"], 2)
        self.assertEqual(comps["C-300"], 5)

    def test_update_product_scales_down_and_rounds(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 3, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_component(self.conn, parent, bolt, 1)

        # 3 -> 1 is a factor of 1/3; 1 * 1/3 rounds to 0.33333.
        db.update_product(self.conn, parent, "A-100", "Widget", 1, "gab.")
        self.assertEqual(db.list_components(self.conn, parent)[0]["quantity"], 0.33333)

    def test_update_product_without_quantity_change_leaves_nested(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 2, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_component(self.conn, parent, bolt, 5)

        # Only the name changes; quantity stays 2, so nested codes are untouched.
        db.update_product(self.conn, parent, "A-100", "Renamed", 2, "gab.")
        self.assertEqual(db.list_components(self.conn, parent)[0]["quantity"], 5)

    def test_update_product_from_zero_quantity_skips_scaling(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 0, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        db.add_component(self.conn, parent, bolt, 5)

        # No baseline to scale from (0 -> 4), so nested codes are left as-is.
        db.update_product(self.conn, parent, "A-100", "Widget", 4, "gab.")
        self.assertEqual(db.list_components(self.conn, parent)[0]["quantity"], 5)

    def test_quantities_rounded_to_five_decimals(self) -> None:
        pid = db.add_product(self.conn, "A-100", "Widget", 1.234567, "gab.")
        self.assertEqual(db.get_product(self.conn, pid)["quantity"], 1.23457)

        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        comp_id = db.add_component(self.conn, pid, bolt, 0.123456)
        self.assertEqual(db.list_components(self.conn, pid)[0]["quantity"], 0.12346)

        db.update_component(self.conn, comp_id, 9.876543)
        self.assertEqual(db.list_components(self.conn, pid)[0]["quantity"], 9.87654)

    def test_format_quantity(self) -> None:
        # At least 2 decimals, at most 5, trailing zeros dropped in between.
        self.assertEqual(db.format_quantity(1), "1.00")
        self.assertEqual(db.format_quantity(1.3), "1.30")
        self.assertEqual(db.format_quantity(1.30000), "1.30")
        self.assertEqual(db.format_quantity(1.2345), "1.2345")
        self.assertEqual(db.format_quantity(1.23456), "1.23456")
        self.assertEqual(db.format_quantity(1.234567), "1.23457")  # rounded to 5
        self.assertEqual(db.format_quantity(0), "0.00")

    def test_delete_product_cascades_to_components(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 1, "gab.")
        db.add_component(self.conn, parent, bolt, 5)

        db.delete_product(self.conn, parent)
        self.assertIsNone(db.get_product(self.conn, parent))
        self.assertEqual(db.list_components(self.conn, parent), [])

    # ----- nested codes -------------------------------------------------

    def test_add_and_list_components_with_resolved_name_and_unit(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        resin = db.add_product(self.conn, "C-300", "Resin", 0, "kg")
        db.add_component(self.conn, parent, bolt, 5)
        db.add_component(self.conn, parent, resin, 2.3)

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
        db.add_component(self.conn, parent, bolt, 5)
        self.assertEqual(db.list_components(self.conn, parent)[0]["unit"], "kg")

        db.update_product(self.conn, bolt, "B-200", "Bolt", 0, "gab.")
        self.assertEqual(db.list_components(self.conn, parent)[0]["unit"], "gab.")

    def test_renaming_code_is_reflected_in_nested_references(self) -> None:
        # References are by id, so renaming a position's code is followed
        # automatically and never orphans the recipes that nest it.
        parent = db.add_product(self.conn, "A-100", "Recipe", 1, "kg")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 1, "kg")
        db.add_component(self.conn, parent, bolt, 5)

        db.update_product(self.conn, bolt, "B-999", "Bolt", 1, "kg")

        comp = db.list_components(self.conn, parent)[0]
        self.assertEqual(comp["child_code"], "B-999")     # reference followed
        self.assertEqual(comp["child_name"], "Bolt")       # still resolves
        self.assertEqual(comp["quantity"], 5)              # unchanged

    def test_nested_code_must_reference_existing_position(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        with self.assertRaises(ValueError):
            db.add_component(self.conn, parent, 9999, 1)  # no such product id

    def test_position_cannot_nest_itself(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        with self.assertRaises(ValueError):
            db.add_component(self.conn, parent, parent, 1)

    def test_add_component_rejects_indirect_cycle(self) -> None:
        a = db.add_product(self.conn, "A-100", "A", 1, "kg")
        b = db.add_product(self.conn, "B-200", "B", 1, "kg")
        db.add_component(self.conn, a, b, 1)            # A contains B
        with self.assertRaises(ValueError):
            db.add_component(self.conn, b, a, 1)        # B contains A -> cycle

    def test_deleting_child_removes_nested_lines(self) -> None:
        # Referencing by id means deleting an ingredient removes the nested
        # lines that used it (no more orphaned "(unknown)" rows).
        recipe = db.add_product(self.conn, "A-100", "Recipe", 1, "kg")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 1, "kg")
        db.add_component(self.conn, recipe, bolt, 5)
        self.assertEqual(len(db.list_components(self.conn, recipe)), 1)

        db.delete_product(self.conn, bolt)
        self.assertEqual(db.list_components(self.conn, recipe), [])

    def test_update_component_changes_only_quantity(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "kg")
        comp_id = db.add_component(self.conn, parent, bolt, 5)

        db.update_component(self.conn, comp_id, 12)

        comp = db.list_components(self.conn, parent)[0]
        self.assertEqual(comp["quantity"], 12)
        self.assertEqual(comp["unit"], "kg")  # still the position's unit
        self.assertEqual(comp["child_code"], "B-200")  # reference unchanged

    def test_delete_component(self) -> None:
        parent = db.add_product(self.conn, "A-100", "Widget", 1, "gab.")
        bolt = db.add_product(self.conn, "B-200", "Bolt", 0, "gab.")
        comp_id = db.add_component(self.conn, parent, bolt, 5)

        db.delete_component(self.conn, comp_id)
        self.assertEqual(db.list_components(self.conn, parent), [])

    def test_components_isolated_per_product(self) -> None:
        first = db.add_product(self.conn, "A-100", "First", 1, "gab.")
        second = db.add_product(self.conn, "B-200", "Second", 1, "gab.")
        child = db.add_product(self.conn, "C-300", "Child", 0, "gab.")
        db.add_component(self.conn, first, child, 1)

        self.assertEqual(len(db.list_components(self.conn, first)), 1)
        self.assertEqual(len(db.list_components(self.conn, second)), 0)

    # ----- migrations of the components table ---------------------------

    def test_init_db_migrates_child_code_to_product_id(self) -> None:
        # A database that still references nested codes by their code string,
        # including one row whose code matches no position (already orphaned).
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
                FOREIGN KEY (parent_product_id)
                    REFERENCES products (id) ON DELETE CASCADE
            );
            INSERT INTO products (code, name, quantity, unit)
                VALUES ('A-100', 'Recipe', 1, 'kg'), ('B-200', 'Bolt', 1, 'kg');
            INSERT INTO components (parent_product_id, child_code, quantity)
                VALUES (1, 'B-200', 5), (1, 'GONE', 9);
            """
        )
        conn.commit()

        db.init_db(conn)

        columns = [r["name"] for r in conn.execute("PRAGMA table_info(components)")]
        self.assertIn("child_product_id", columns)
        self.assertNotIn("child_code", columns)

        comps = db.list_components(conn, 1)
        self.assertEqual(len(comps), 1)  # the orphaned 'GONE' row was dropped
        self.assertEqual(comps[0]["child_code"], "B-200")  # resolved by id
        self.assertEqual(comps[0]["quantity"], 5)
        conn.close()

    def test_init_db_migrates_away_old_component_unit_column(self) -> None:
        # A pre-migration database that stored both a per-code unit and the
        # legacy child_code reference; both legacy columns should be gone.
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
                VALUES ('A-100', 'Widget', 1, 'gab.'), ('B-200', 'Bolt', 1, 'kg');
            INSERT INTO components (parent_product_id, child_code, quantity, unit)
                VALUES (1, 'B-200', 5, 'kg');
            """
        )
        conn.commit()

        db.init_db(conn)  # drops components.unit AND migrates to child_product_id

        columns = [r["name"] for r in conn.execute("PRAGMA table_info(components)")]
        self.assertNotIn("unit", columns)
        self.assertNotIn("child_code", columns)
        self.assertIn("child_product_id", columns)

        comp = db.list_components(conn, 1)[0]
        self.assertEqual(comp["child_code"], "B-200")  # resolved from id
        self.assertEqual(comp["quantity"], 5)
        conn.close()


if __name__ == "__main__":
    unittest.main()

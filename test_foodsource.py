"""Tests for the pure parser in :mod:`foodsource`.

These never touch the network — they feed sample Open Food Facts product dicts
(the shape the API returns) to ``parse_off_product`` and check the mapping. Run
them with ``python -m unittest``.
"""

import unittest

import foodsource


class ParseOffProductTests(unittest.TestCase):
    def test_maps_nutriments_to_six_fields(self) -> None:
        product = {
            "code": "4750123456789",
            "product_name": "Wheat Flour",
            "brands": "Acme",
            "nutriments": {
                "fat_100g": 1.2,
                "saturated-fat_100g": 0.3,
                "carbohydrates_100g": 72,
                "sugars_100g": 1.5,
                "proteins_100g": 10,
                "salt_100g": 0.01,
            },
        }
        result = foodsource.parse_off_product(product)
        self.assertEqual(result["code"], "4750123456789")
        self.assertEqual(result["name"], "Wheat Flour (Acme)")
        n = result["nutrition"]
        self.assertEqual(n["fat"], 1.2)
        self.assertEqual(n["saturated_fat"], 0.3)
        self.assertEqual(n["carbs"], 72)
        self.assertEqual(n["sugar"], 1.5)
        self.assertEqual(n["protein"], 10)
        self.assertEqual(n["salt"], 0.01)

    def test_missing_nutriments_become_none(self) -> None:
        result = foodsource.parse_off_product(
            {"product_name": "Mystery", "nutriments": {"fat_100g": 5}}
        )
        n = result["nutrition"]
        self.assertEqual(n["fat"], 5)
        self.assertIsNone(n["protein"])
        self.assertIsNone(n["salt"])

    def test_salt_falls_back_to_sodium(self) -> None:
        result = foodsource.parse_off_product({"nutriments": {"sodium_100g": 0.4}})
        self.assertAlmostEqual(result["nutrition"]["salt"], 1.0)  # 0.4 * 2.5

    def test_string_values_are_parsed_blank_is_missing(self) -> None:
        result = foodsource.parse_off_product(
            {"nutriments": {"fat_100g": "2.5", "carbohydrates_100g": ""}}
        )
        self.assertEqual(result["nutrition"]["fat"], 2.5)
        self.assertIsNone(result["nutrition"]["carbs"])

    def test_brand_not_duplicated_in_name(self) -> None:
        result = foodsource.parse_off_product(
            {"product_name": "Acme Flour", "brands": "Acme"}
        )
        self.assertEqual(result["name"], "Acme Flour")  # brand already present

    def test_name_falls_back_through_alternatives(self) -> None:
        result = foodsource.parse_off_product(
            {"generic_name": "Flour", "nutriments": {}}
        )
        self.assertEqual(result["name"], "Flour")

    def test_no_name_and_no_brand_is_blank(self) -> None:
        result = foodsource.parse_off_product({"nutriments": {}})
        self.assertEqual(result["name"], "")
        self.assertTrue(all(v is None for v in result["nutrition"].values()))


if __name__ == "__main__":
    unittest.main()
